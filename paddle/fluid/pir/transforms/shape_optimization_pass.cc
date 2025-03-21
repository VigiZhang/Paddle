// Copyright (c) 2023 PaddlePaddle Authors. All Rights Reserved.
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

#include "paddle/fluid/pir/transforms/shape_optimization_pass.h"
#include "paddle/common/flags.h"
#include "paddle/fluid/pir/dialect/operator/ir/pd_op.h"
#include "paddle/pir/include/core/dialect.h"
#include "paddle/pir/include/core/ir_printer.h"
#include "paddle/pir/include/dialect/shape/ir/shape_attribute.h"
#include "paddle/pir/include/dialect/shape/ir/shape_dialect.h"
#include "paddle/pir/include/pass/pass_manager.h"
#include "paddle/pir/include/pass/pass_registry.h"

COMMON_DECLARE_bool(pir_apply_shape_optimization_pass);

constexpr int vlog_level = 3;

// TODO(zhangbopd): Some op results infered by InferSymbolicShape is NOT consist
// with the result infered by InferMeta and should be fixed.
namespace {
bool NeedCheckInferSymbolicWithInferMeta(const std::string& op_name,
                                         size_t result_idx) {
  static std::unordered_map<std::string, std::unordered_set<int>> blacklist{
      {"pd_op.reshape", {1}},
      {"pd_op.empty", {0}},
  };
  const auto& iter = blacklist.find(op_name);
  if (iter == blacklist.end()) return true;
  return iter->second.count(result_idx) == 0;
}
}  // namespace

namespace pir {
namespace {

using PassPipelineRunner =
    std::function<bool(pir::PassManager&, pir::ModuleOp)>;

void PrintProgram(pir::ModuleOp m, std::string msg) {
  ShapeConstraintIRAnalysis& shape_analysis =
      ShapeAnalysisManager::Instance().Get(m.program());
  if (VLOG_IS_ON(vlog_level)) {
    std::cerr << "===================== [ShapeDialect]" << msg
              << " =====================\n"
              << pir::CustomPrintHelper(*m.program(),
                                        shape_analysis.PrintHook())
              << std::endl;
  }
}

std::string PrintOperationWithNoRegion(Operation* op) {
  std::ostringstream os;
  pir::IrPrinter printer(os);

  // print OpResults
  os << "(";
  auto num_op_result = op->num_results();
  for (size_t idx = 0; idx < num_op_result; idx++) {
    os << "%op_" << op->id() << "_" << idx;
    if (idx < num_op_result - 1) os << ", ";
  }
  os << ")";

  os << " =";

  // print OpName & OpId
  os << " \"" << op->name() << "(op_" << op->id() << ")"
     << "\"";

  // print OpOperands
  os << " (";
  auto num_op_operands = op->num_operands();
  for (size_t idx = 0; idx < num_op_operands; idx++) {
    const pir::Value& input = op->operand_source(idx);
    if (input.defining_op()) {
      os << "op_" << input.defining_op()->id() << "_"
         << input.dyn_cast<pir::OpResult>().index();
    } else {
      os << "op_NULL";
    }
    if (idx < num_op_operands - 1) os << ", ";
  }
  os << ")";

  printer.PrintAttributeMap(op);
  os << " :";

  // PrintOpSignature
  printer.PrintOperandsType(op);
  os << " -> ";

  printer.PrintOpReturnType(op);

  return os.str();
}

void PrintOpInfo(pir::Operation* op) {
  if (VLOG_IS_ON(vlog_level)) {
    VLOG(vlog_level) << op->name() << "(op_id: op_" << op->id()
                     << ", num_results=" << op->num_results() << ")"
                     << " has InferSymbolicShapeInterface.\n\t"
                     << PrintOperationWithNoRegion(op);
    if (op->name() == "cinn_op.group") {
      std::cerr << "<<<<<<<<<<<<<<<<<<<< " << op->name() << "(op_id: op_"
                << op->id() << ") START..." << std::endl;
    }
  }
}

void DebugPrintOpInfo(
    pir::Operation* op,
    pir::ShapeConstraintIRAnalysis* shape_analysis = nullptr) {
  std::ostringstream print_stream;
  for (uint32_t i = 0; i < op->num_results(); ++i) {
    const auto& res = op->result(i);
    print_stream << "\tresult(" << res.dyn_cast<pir::OpResult>().index() << ") "
                 << "ShapeOrData: {";

    if (shape_analysis != nullptr) {
      auto shape_data = shape_analysis->GetShapeOrDataForValue(res);
      if (shape_data.isa<symbol::TensorListShapeOrDataDimExprs>()) continue;
      print_stream << "shape: [";

      for (size_t i = 0; i < shape_data.shape().size(); ++i) {
        if (i != shape_data.shape().size() - 1) {
          print_stream << symbol::ToString(shape_data.shape()[i]) << ",";
        } else {
          print_stream << symbol::ToString(shape_data.shape()[i]);
        }
      }

      print_stream << "], data: [";
      if (shape_data.data().has_value()) {
        for (size_t i = 0; i < shape_data.data().value().size(); ++i) {
          if (i != shape_data.data().value().size() - 1) {
            print_stream << symbol::ToString(shape_data.data().value()[i])
                         << ",";
          } else {
            print_stream << symbol::ToString(shape_data.data().value()[i]);
          }
        }
      } else {
        print_stream << "nullopt";
      }

      print_stream << "]";
    }
    print_stream << " }\n";
  }
  if (VLOG_IS_ON(vlog_level)) {
    std::cerr << print_stream.str();
  }
}

void CheckInferSymWithInferMeta(
    pir::Operation* op,
    pir::ShapeConstraintIRAnalysis* shape_analysis = nullptr) {
  for (uint32_t i = 0; i < op->num_results(); ++i) {
    const auto& res = op->result(i);
    std::ostringstream print_stream;

    // InferMeta funcs of some Ops are not corrrect now, we don't check them.
    if (!NeedCheckInferSymbolicWithInferMeta(op->name(), i)) continue;

    if (res.type().isa<paddle::dialect::DenseTensorType>()) {
      const std::vector<int64_t>& infer_meta_shape = common::vectorize(
          res.type().dyn_cast<paddle::dialect::DenseTensorType>().dims());
      const std::vector<symbol::DimExpr>& infer_sym_shape =
          shape_analysis->GetShapeOrDataForValue(res).shape();

      // Check rank.
      if (infer_meta_shape.size() != infer_sym_shape.size()) {
        std::ostringstream print_stream;
        print_stream << "Warning : Check InferSymbolicShape for " << op->name()
                     << " (op_" << op->id() << ") "
                     << " carefully! rank of infer_meta_shape is ["
                     << infer_meta_shape.size()
                     << "], but rank of infer_sym_shape is ["
                     << infer_sym_shape.size() << "].";
        VLOG(vlog_level) << print_stream.str();
        continue;
      }

      // Check each dim.
      for (size_t i = 0; i < infer_meta_shape.size(); ++i) {
        // Check Static shape should NOT be a symbol.
        if (infer_meta_shape[i] != -1) {
          if (!infer_sym_shape[i].isa<int64_t>()) {
            std::ostringstream print_stream;
            print_stream
                << "Warning : Check InferSymbolicShape for " << op->name()
                << " (op_" << op->id() << ") "
                << " carefully! "
                << "shape[" << i
                << "] of infer_sym_shape shoule be int64_t NOT a symbol!";
            VLOG(vlog_level) << print_stream.str();
            continue;
          }

          // Check Static shape should be consist.
          if (infer_meta_shape[i] != infer_sym_shape[i].dyn_cast<int64_t>()) {
            std::ostringstream print_stream;
            print_stream << "Warning : Check InferSymbolicShape for "
                         << op->name() << " (op_" << op->id() << ") "
                         << " carefully! "
                         << "infer_sym_shape is [" << infer_meta_shape[i]
                         << "], but infer_meta_shape is ["
                         << infer_sym_shape[i].dyn_cast<int64_t>() << "].";
            VLOG(vlog_level) << print_stream.str();
          }
        }
      }
    }
  }
}

void InferSymExprForAllValues(ModuleOp module_op) {
  ShapeConstraintIRAnalysis& shape_analysis =
      ShapeAnalysisManager::Instance().Get(module_op.program());
  shape_analysis.Init();
  for (uint32_t i = 0; i < module_op->num_regions(); i++) {
    for (auto& block : module_op->region(i)) {
      InferSymExprForBlock(block, &shape_analysis);
    }
  }
}

class ShapeOptimizationPass : public pir::Pass {
 public:
  ShapeOptimizationPass() : pir::Pass("shape_optimization_pass", 0) {}

  void Run(pir::Operation* op) override {
    VLOG(vlog_level)
        << "===================== ShapeOptimizationPass Run start... "
           "=====================";
    auto module_op = op->dyn_cast<pir::ModuleOp>();
    PADDLE_ENFORCE_EQ(module_op.name(),
                      "builtin.module",
                      phi::errors::InvalidArgument(
                          "ShapeOptimizationPass should run on module op."));
    PrintProgram(module_op, "Origin Program");

    InferSymExprForAllValues(module_op);
    // Runner is for Canonicalizer.
    PassPipelineRunner runner = [](pir::PassManager& pm, pir::ModuleOp m) {
      pm.EnableIRPrinting();
      return pm.Run(m.program());
    };

    PrintProgram(module_op, "ShapeOptimizationPass Program");
    VLOG(vlog_level) << "===================== ShapeOptimizationPass Run End. "
                        "=====================";
  }

  bool CanApplyOn(pir::Operation* op) const override {
    return op->isa<pir::ModuleOp>() && op->num_regions() > 0;
  }
};

}  // namespace

void InferSymExprForBlock(const Block& block,
                          ShapeConstraintIRAnalysis* shape_analysis) {
  for (auto& op : block) {
    auto infer_symbolic_shape_interface =
        op.dyn_cast<paddle::dialect::InferSymbolicShapeInterface>();
    if (infer_symbolic_shape_interface) {
      PrintOpInfo(&op);
      PADDLE_ENFORCE_EQ(
          infer_symbolic_shape_interface.InferSymbolicShape(shape_analysis),
          true,
          "InferSymbolicShape for %s failed.",
          op.name());

      if (op.num_results() > 0) {
        // TODO(lanxianghit): deal with the ops which have more than 1
        // ACTUAL results
        pir::shape::SetShapeAttrForOp(
            &op, shape_analysis->GetShapeOrDataForValue(op.result(0)));
      }
    } else {
      PADDLE_THROW(phi::errors::Unimplemented(
          op.name() + " DOES NOT have InferSymbolicShapeInterface!"));
    }
    DebugPrintOpInfo(&op, shape_analysis);
    CheckInferSymWithInferMeta(&op, shape_analysis);
  }
}

std::unique_ptr<Pass> CreateShapeOptimizationPass() {
  return std::make_unique<ShapeOptimizationPass>();
}

}  // namespace pir

namespace pir::shape {

bool HasDynamicShape(const pir::Program& program) {
  for (const auto& op : *program.block()) {
    if (op.isa<pir::CombineOp>()) {
      continue;
    }
    for (uint32_t i = 0; i < op.num_results(); ++i) {
      if (op.result(i) && op.result(i).type()) {
        auto shape_type =
            op.result(i).type().dyn_cast<pir::ShapedTypeInterface>();
        if (shape_type && shape_type.IsDynamicShape()) {
          VLOG(vlog_level) << "###### HasDynamicShape == true";
          return true;
        }
      }
    }
  }
  VLOG(vlog_level) << "###### HasDynamicShape == false";
  return false;
}

void AddShapeOptimizationPass(
    std::shared_ptr<pir::PassManager>& pass_manager,  // NOLINT
    pir::Program& program) {                          // NOLINT
  pir::IrContext* ctx = pir::IrContext::Instance();
  ctx->GetOrRegisterDialect<pir::shape::ShapeDialect>();
  if (HasDynamicShape(program) && FLAGS_pir_apply_shape_optimization_pass) {
    pass_manager->AddPass(pir::CreateShapeOptimizationPass());
  }
}

}  // namespace pir::shape

REGISTER_IR_PASS(shape_optimization_pass, pir::ShapeOptimizationPass);

file(GLOB_RECURSE cinn_transforms_srcs "*.cc")

set(cinn_transforms_deps
    pir
    drr
    op_dialect
    cinn_op_dialect
    op_dialect_vjp
    cinn_runtime_dialect
    pir_compiler)

cinn_cc_library(cinn_transforms SRCS ${cinn_transforms_srcs} DEPS
                ${cinn_transforms_deps})

cc_library(
  add_cinn_pass
  SRCS add_cinn_pass.cc
  DEPS op_dialect pir cinn_op_dialect cinnapi pir_transforms cinn_transforms)

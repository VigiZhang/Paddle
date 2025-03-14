# Copyright (c) 2023 PaddlePaddle Authors. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import unittest

import numpy as np

import paddle
import paddle.nn.functional as F
from paddle.framework import core
from paddle.static import InputSpec


def apply_to_static(net, use_cinn, input_spec=None):
    build_strategy = paddle.static.BuildStrategy()
    build_strategy.build_cinn_pass = use_cinn
    return paddle.jit.to_static(
        net,
        input_spec=input_spec,
        build_strategy=build_strategy,
        full_graph=True,
    )


def log_softmax_net(x):
    return F.log_softmax(x)


def any_net(x):
    return paddle.any(x)


def embedding_net(x):
    w = np.array(
        [
            [0, 1, 2],
            [3, 4, 5],
            [6, 7, 8],
            [9, 10, 11],
            [12, 13, 14],
            [15, 16, 17],
            [18, 19, 20],
            [21, 22, 23],
            [24, 25, 26],
            [27, 28, 29],
        ],
        dtype=np.float32,
    )
    w = paddle.to_tensor(w)
    return F.embedding(x, w, padding_idx=1)


def full_like_net(x):
    return paddle.full_like(x, 1)


def stack_net(x):
    y = x + 1
    return paddle.stack([x, y], axis=0)


def tile_net1(x):
    y = paddle.tile(x, repeat_times=[2, 5])
    return y


def tile_net2(x):
    y = paddle.tile(x, repeat_times=[3, 2, 5])
    return y


def index_sample_net(x, index):
    return paddle.index_sample(x, index)


def swiglu_net1(x, y):
    return paddle.incubate.nn.functional.swiglu(x, y)


def swiglu_net2(x):
    return paddle.incubate.nn.functional.swiglu(x)


def layer_norm_net1(x):
    return paddle.nn.functional.layer_norm(x, x.shape[1:])


def flatten_net(x):
    return paddle.flatten(x, 1, 2)


class TestPrimBase(unittest.TestCase):
    def setUp(self):
        np.random.seed(2023)
        self.dtype = "float32"
        self.x_shape = [1, 300, 4096]
        self.init_x_shape = [None, None, 4096]
        self.x = np.random.random(self.x_shape).astype(self.dtype)
        self.net = log_softmax_net
        self.necessary_ops = "pd_op.log_softmax"
        self.enable_cinn = False
        self.tol = 1e-6

    def base_net(self, flag=None):
        if flag == "prim":
            core._set_prim_all_enabled(True)
        x = paddle.to_tensor(self.x)
        if flag == "prim":
            fn = apply_to_static(
                self.net,
                use_cinn=self.enable_cinn,
                input_spec=[
                    InputSpec(shape=self.init_x_shape, dtype='float32'),
                ],
            )
            fn.eval()
        else:
            fn = self.net
        res = fn(x)

        if flag == "prim":
            ops = [
                op.name()
                for op in fn.program_cache.last()[-1][-1]
                .infer_program.program.global_block()
                .ops
            ]
            assert self.necessary_ops not in ops
            core._set_prim_all_enabled(False)
        return res

    def test_prim_all_dynamic(self):
        res_ref = self.base_net()
        res = self.base_net("prim")
        for ref, actual in zip(res_ref, res):
            np.testing.assert_allclose(
                ref, actual, rtol=self.tol, atol=self.tol
            )


class TestPrimAny(TestPrimBase):
    def setUp(self):
        np.random.seed(2023)
        self.dtype = "bool"
        self.x_shape = [1, 300, 4096]
        self.init_x_shape = [None, None, 4096]
        self.x = np.random.random(self.x_shape).astype(self.dtype)
        self.net = any_net
        self.necessary_ops = "pd_op.any"
        self.enable_cinn = False
        self.tol = 1e-6


class TestEmbedding(TestPrimBase):
    def setUp(self):
        np.random.seed(2023)
        self.dtype = "int"
        self.x_shape = [1, 300, 4096]
        self.init_x_shape = [None, None, 4096]
        self.x = np.random.randint(0, 10, size=self.x_shape)
        self.net = embedding_net
        self.necessary_ops = "pd_op.embedding"
        self.enable_cinn = False
        self.tol = 1e-6


class TestPrimFullLike(TestPrimBase):
    def setUp(self):
        np.random.seed(2023)
        self.dtype = "float32"
        self.x_shape = [1, 300, 4096]
        self.init_x_shape = [None, None, 4096]
        self.x = np.random.random(self.x_shape).astype(self.dtype)
        self.net = full_like_net
        self.necessary_ops = "pd_op.full_like"
        self.enable_cinn = False
        self.tol = 1e-6


class TestPrimStack(TestPrimBase):
    def setUp(self):
        np.random.seed(2023)
        self.dtype = "float32"
        self.x_shape = [1, 300, 4096]
        self.init_x_shape = [None, None, 4096]
        self.x = np.random.random(self.x_shape).astype(self.dtype)
        self.net = stack_net
        self.necessary_ops = "pd_op.stack"
        self.enable_cinn = False
        self.tol = 1e-6


class TestPrimTile(TestPrimBase):
    def setUp(self):
        np.random.seed(2023)
        self.dtype = "float32"
        self.x_shape = [1, 300, 4096]
        self.init_x_shape = [None, None, 4096]
        self.x = np.random.random(self.x_shape).astype(self.dtype)
        self.net = tile_net1
        self.necessary_ops = "pd_op.tile"
        self.enable_cinn = False
        self.tol = 1e-6


class TestPrimTile2(TestPrimBase):
    def setUp(self):
        np.random.seed(2023)
        self.dtype = "float32"
        self.x_shape = [300, 4096]
        self.init_x_shape = [None, 4096]
        self.x = np.random.random(self.x_shape).astype(self.dtype)
        self.net = tile_net2
        self.necessary_ops = "pd_op.tile"
        self.enable_cinn = False
        self.tol = 1e-6


class TestPrimTwo(unittest.TestCase):
    def setUp(self):
        np.random.seed(2023)
        self.shape_x = [300, 4096]
        self.shape_y = [300, 2048]
        self.dtype_x = "float32"
        self.dtype_y = int
        self.init_x_shape = [None, 4096]
        self.init_y_shape = [None, 2048]
        self.x = np.random.random(self.shape_x).astype(self.dtype_x)
        self.y = np.random.random(self.shape_y).astype(self.dtype_y)
        self.net = index_sample_net
        self.necessary_ops = "pd_op.index_sample"
        self.enable_cinn = False
        self.tol = 1e-6

    def base_net(self, flag=None):
        x = paddle.to_tensor(self.x)
        y = paddle.to_tensor(self.y)
        if flag == "prim":
            core._set_prim_all_enabled(True)
            fn = apply_to_static(
                self.net,
                use_cinn=self.enable_cinn,
                input_spec=[
                    InputSpec(shape=self.init_x_shape, dtype=self.dtype_x),
                    InputSpec(shape=self.init_y_shape, dtype=self.dtype_y),
                ],
            )
            fn.eval()
        else:
            fn = self.net
        res = fn(x, y)

        if flag == "prim":
            ops = [
                op.name()
                for op in fn.program_cache.last()[-1][-1]
                .infer_program.program.global_block()
                .ops
            ]
            assert self.necessary_ops not in ops
            core._set_prim_all_enabled(False)
        return res

    def test_prim_all_dynamic(self):
        res_ref = self.base_net()
        res = self.base_net("prim")
        for ref, actual in zip(res_ref, res):
            np.testing.assert_allclose(ref, actual, rtol=self.tol)


class TestPrimTwoIndexSample(TestPrimTwo):
    def setUp(self):
        np.random.seed(2023)
        self.shape_x = [300, 4096]
        self.shape_y = [300, 2048]
        self.dtype_x = "float32"
        self.dtype_y = int
        self.init_x_shape = [None, 4096]
        self.init_y_shape = [300, 2048]
        self.x = np.random.random(self.shape_x).astype(self.dtype_x)
        self.y = np.random.random(self.shape_y).astype(self.dtype_y)
        self.net = index_sample_net
        self.necessary_ops = "pd_op.index_sample"
        self.enable_cinn = False
        self.tol = 1e-6


class TestPrimSwiglu1(TestPrimTwo):
    def setUp(self):
        np.random.seed(2023)
        self.shape_x = [300, 4096]
        self.shape_y = [300, 4096]
        self.dtype_x = "float32"
        self.dtype_y = "float32"
        self.init_x_shape = [None, None]
        self.init_y_shape = [None, None]
        self.x = np.random.random(self.shape_x).astype(self.dtype_x)
        self.y = np.random.random(self.shape_y).astype(self.dtype_y)
        self.net = swiglu_net1
        self.necessary_ops = "pd_op.swiglu"
        self.enable_cinn = False
        self.tol = 1e-6


class TestPrimSwiglu2(TestPrimBase):
    def setUp(self):
        np.random.seed(2023)
        self.shape_x = [300, 4096]
        self.dtype_x = "float32"
        self.init_x_shape = [None, 4096]
        self.x = np.random.random(self.shape_x).astype(self.dtype_x)
        self.net = swiglu_net2
        self.necessary_ops = "pd_op.swiglu"
        self.enable_cinn = False
        self.tol = 1e-6


class TestPrimLayernorm(TestPrimBase):
    def setUp(self):
        np.random.seed(2023)
        self.shape_x = [2, 32, 128]
        self.dtype_x = "float32"
        self.init_x_shape = [None, None, None]
        self.x = np.random.random(self.shape_x).astype(self.dtype_x)
        self.net = layer_norm_net1
        self.necessary_ops = "pd_op.layer_norm"
        self.enable_cinn = False
        self.tol = 5e-6


class TestPrimFlatten1(TestPrimBase):
    def setUp(self):
        np.random.seed(2023)
        self.dtype = "float32"
        self.x_shape = [3, 100, 100, 4]
        self.init_x_shape = [3, None, None, 4]
        self.x = np.random.random(self.x_shape).astype(self.dtype)
        self.net = flatten_net
        self.necessary_ops = "pd_op.flatten"
        self.enable_cinn = False
        self.tol = 1e-6


class TestPrimFlatten2(TestPrimBase):
    def setUp(self):
        np.random.seed(2023)
        self.dtype = "float32"
        self.x_shape = [3, 100, 100, 640]
        self.init_x_shape = [None, None, None, 640]
        self.x = np.random.random(self.x_shape).astype(self.dtype)
        self.net = flatten_net
        self.necessary_ops = "pd_op.flatten"
        self.enable_cinn = False
        self.tol = 1e-6


if __name__ == "__main__":
    unittest.main()

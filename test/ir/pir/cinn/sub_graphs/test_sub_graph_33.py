# Copyright (c) 2024 PaddlePaddle Authors. All Rights Reserved.
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

# repo: PaddleClas
# model: ppcls^configs^ImageNet^RedNet^RedNet38
# api:paddle.nn.functional.conv._conv_nd||method:reshape||method:unsqueeze||api:paddle.nn.functional.common.unfold||method:reshape||method:__mul__||method:sum||method:reshape
import unittest

import numpy as np

import paddle


class LayerCase(paddle.nn.Layer):
    def __init__(self):
        super().__init__()
        self.parameter_0 = self.create_parameter(
            shape=[784],
            dtype=paddle.float32,
        )
        self.parameter_1 = self.create_parameter(
            shape=[784, 64, 1, 1],
            dtype=paddle.float32,
        )

    def forward(
        self,
        var_0,  # (shape: [10, 64, 14, 14], dtype: paddle.float32, stop_gradient: False)
        var_1,  # (shape: [10, 256, 14, 14], dtype: paddle.float32, stop_gradient: False)
    ):
        var_2 = paddle.nn.functional.conv._conv_nd(
            var_0,
            self.parameter_1,
            bias=self.parameter_0,
            stride=[1, 1],
            padding=[0, 0],
            padding_algorithm='EXPLICIT',
            dilation=[1, 1],
            groups=1,
            data_format='NCHW',
            channel_dim=1,
            op_type='conv2d',
            use_cudnn=True,
        )
        var_3 = var_2.reshape((10, 16, 49, 14, 14))
        var_4 = var_3.unsqueeze(2)
        var_5 = paddle.nn.functional.common.unfold(var_1, 7, 1, 3, 1)
        var_6 = var_5.reshape((10, 16, 16, 49, 14, 14))
        var_7 = var_4 * var_6
        var_8 = var_7.sum(axis=3)
        var_9 = var_8.reshape((10, 256, 14, 14))
        return var_9


class TestLayer(unittest.TestCase):
    def setUp(self):
        self.inputs = (
            paddle.rand(shape=[10, 64, 14, 14], dtype=paddle.float32),
            paddle.rand(shape=[10, 256, 14, 14], dtype=paddle.float32),
        )
        self.net = LayerCase()

    def train(self, net, to_static, with_prim=False, with_cinn=False):
        if to_static:
            paddle.set_flags({'FLAGS_prim_all': with_prim})
            if with_cinn:
                build_strategy = paddle.static.BuildStrategy()
                build_strategy.build_cinn_pass = True
                net = paddle.jit.to_static(
                    net, build_strategy=build_strategy, full_graph=True
                )
            else:
                net = paddle.jit.to_static(net, full_graph=True)
        paddle.seed(123)
        outs = net(*self.inputs)
        return outs

    def test_ast_prim_cinn(self):
        st_out = self.train(self.net, to_static=True)
        # NOTE(Aurelius84): atol only satisfy 1e-5 under with_cinn=True
        cinn_out = self.train(
            self.net, to_static=True, with_prim=True, with_cinn=True
        )
        for st, cinn in zip(
            paddle.utils.flatten(st_out), paddle.utils.flatten(cinn_out)
        ):
            np.testing.assert_allclose(st.numpy(), cinn.numpy(), atol=1e-5)


# if __name__ == '__main__':
#     unittest.main()

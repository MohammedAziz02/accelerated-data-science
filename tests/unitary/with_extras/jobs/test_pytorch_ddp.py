#!/usr/bin/env python

# Copyright (c) 2023 Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at https://oss.oracle.com/licenses/upl/
import os
import sys
import unittest
from unittest import mock
from ads.jobs import PyTorchDistributedRuntime, DataScienceJob, DataScienceJobRun
from ads.jobs.builders.infrastructure.dsc_job_runtime import (
    PyTorchDistributedRuntimeHandler as Handler,
)
from ads.jobs.builders.runtimes.pytorch_runtime import (
    PyTorchDistributedArtifact,
    GitPythonArtifact,
)
from ads.opctl.distributed.common import cluster_config_helper as cluster
from ads.jobs.templates import driver_utils as utils
from ads.jobs.templates import driver_pytorch as driver


class PyTorchRunnerTest(unittest.TestCase):
    TEST_IP = "10.0.0.1"
    TEST_HOST_IP = "10.0.0.100"
    TEST_HOST_OCID = "ocid_host"
    TEST_NODE_OCID = "ocid_node"

    def init_torch_runner(self):
        with mock.patch(
            "ads.jobs.templates.driver_pytorch.TorchRunner.build_c_library"
        ), mock.patch("socket.gethostbyname") as GetHostIP, mock.patch(
            "ads.jobs.DataScienceJobRun.from_ocid"
        ) as GetJobRun:
            GetHostIP.return_value = self.TEST_IP
            GetJobRun.return_value = DataScienceJobRun(id="ocid.abcdefghijk")
            return driver.TorchRunner()

    @mock.patch.dict(os.environ, {driver.CONST_ENV_HOST_JOB_RUN_OCID: TEST_HOST_OCID})
    def test_init_torch_runner_at_node(self):
        runner = self.init_torch_runner()
        self.assertEqual(runner.host_ocid, self.TEST_HOST_OCID)
        self.assertEqual(runner.host_ip, None)

    @mock.patch.dict(os.environ, {driver.CONST_ENV_JOB_RUN_OCID: TEST_NODE_OCID})
    def test_init_torch_runner_at_host(self):
        runner = self.init_torch_runner()
        self.assertEqual(runner.host_ocid, self.TEST_NODE_OCID)
        self.assertEqual(runner.host_ip, self.TEST_IP)

    @mock.patch.dict(os.environ, {driver.CONST_ENV_HOST_JOB_RUN_OCID: TEST_HOST_OCID})
    def test_wait_for_host_ip(self):
        with mock.patch("ads.jobs.DataScienceJobRun.logs") as get_logs:
            get_logs.return_value = [
                {"message": f"{driver.LOG_PREFIX_HOST_IP} {self.TEST_HOST_IP}"}
            ]
            runner = self.init_torch_runner()
            self.assertEqual(runner.host_ip, None)
            runner.wait_for_host_ip_address()
            self.assertEqual(runner.host_ip, self.TEST_HOST_IP)

    @mock.patch.dict(
        os.environ, {driver.CONST_ENV_LAUNCH_CMD: "torchrun train.py --data abc"}
    )
    def test_launch_cmd(self):
        runner = self.init_torch_runner()
        self.assertTrue(runner.launch_cmd_contains("data"))
        self.assertFalse(runner.launch_cmd_contains("data1"))
        self.assertEqual(
            runner.prepare_cmd(prefix="A=1"), "A=1 torchrun train.py --data abc"
        )

    @mock.patch.dict(os.environ, {Handler.CONST_CODE_ENTRYPOINT: "train.py"})
    @mock.patch.object(sys, "argv", ["python", "hello", "--data", "abc"])
    def test_prepare_cmd_with_entrypoint_args(self):
        runner = self.init_torch_runner()
        self.assertEqual(
            runner.prepare_cmd(launch_args=["--key", "val"], prefix="A=1"),
            "A=1 torchrun --key val train.py hello --data abc",
        )


class LazyEvaluateTest(unittest.TestCase):
    def test_lazy_evaluation(self):
        def func(a, b):
            return a + b

        def func_with_error():
            raise ValueError()

        lazy_val = driver.LazyEvaluate(func, 1, 1)
        self.assertEqual(str(lazy_val), "2")

        lazy_val = driver.LazyEvaluate(func_with_error)
        self.assertEqual(str(lazy_val), "ERROR: ")

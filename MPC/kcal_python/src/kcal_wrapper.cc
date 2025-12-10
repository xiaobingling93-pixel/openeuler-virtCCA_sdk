// Copyright (c) Huawei Technologies Co., Ltd. 2025-2025. All rights reserved.

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include <memory>

#include "context_ext.h"
#include "kcal/core/operator_base.h"
#include "kcal/core/operator_manager.h"
#include "kcal/operator/all_operator_register.h"
#include "kcal/operator/kcal_pir.h"
#include "kcal/operator/kcal_psi.h"
#include "kcal/utils/io.h"

namespace py = pybind11;

namespace kcal {

namespace {

void FeedKcalInput(const py::list &pyList, io::KcalInput *kcalInput)
{
    auto *dgString = new (std::nothrow) DG_String[pyList.size()];
    if (!dgString) {
        throw std::bad_alloc();
    }
    for (size_t i = 0; i < pyList.size(); ++i) {
        if (!PyUnicode_Check(pyList[i].ptr())) {
            throw std::runtime_error("need str");
        }

        Py_ssize_t sz;
        const char *utf8 = PyUnicode_AsUTF8AndSize(pyList[i].ptr(), &sz);
        if (!utf8) {
            throw std::bad_alloc();
        }

        dgString[i].str = strdup(utf8);
        dgString[i].size = static_cast<int>(sz) + 1;
    }
    DG_TeeInput **internalInput = kcalInput->GetSecondaryPointer();
    (*internalInput)->data.strings = dgString;
    (*internalInput)->size = pyList.size();
    (*internalInput)->dataType = MPC_STRING;
}

void FeedKcalPairList(const py::list &key, const py::list &value, io::KcalPairList *pairList)
{
    if (key.size() != value.size()) {
        // 打印日志
        throw std::runtime_error("key value size don't match");
    };
    auto size = key.size();
    pairList->Get()->dgPair = new (std::nothrow) DG_Pair[size];
    if (!pairList->Get()->dgPair) {
        throw std::bad_alloc();
    }
    size_t i = 0;
    for (i = 0; i < key.size(); ++i) {
        pairList->Get()->dgPair[i].key = new (std::nothrow) DG_String();
        pairList->Get()->dgPair[i].key = new (std::nothrow) DG_String();
        pairList->Get()->dgPair[i].value = new (std::nothrow) DG_String();
        if (!pairList->Get()->dgPair[i].key || !pairList->Get()->dgPair[i].value) {
            pairList->Get()->size = i + 1;
            throw std::bad_alloc();
        }
        // 填充key
        {
            if (!PyUnicode_Check(key[i].ptr())) {
                throw std::runtime_error("need str");
            }
            Py_ssize_t sz;
            const char *utf8 = PyUnicode_AsUTF8AndSize(key[i].ptr(), &sz);
            if (!utf8) {
                throw std::bad_alloc();
            }
            pairList->Get()->dgPair[i].key->str = strdup(utf8);
            pairList->Get()->dgPair[i].key->str = strdup(utf8);
            pairList->Get()->dgPair[i].key->size = static_cast<int>(sz) + 1;
        }
        // 填充 value
        {
            if (!PyUnicode_Check(value[i].ptr())) {
                throw std::runtime_error("need str");
            }
            Py_ssize_t sz;
            const char *utf8 = PyUnicode_AsUTF8AndSize(value[i].ptr(), &sz);
            if (!utf8) {
                throw std::bad_alloc();
            }
            pairList->Get()->dgPair[i].value->str = strdup(utf8);
            pairList->Get()->dgPair[i].value->str = strdup(utf8);
            pairList->Get()->dgPair[i].value->size = static_cast<int>(sz) + 1;
        }
    }
    pairList->Get()->size = size;
}

void FeedPsiOutput(io::KcalOutput &kcalOutput, py::list &pyList, DG_TeeMode mode)
{
    auto *outPtr = kcalOutput.Get();
    for (size_t i = 0; i < outPtr->size; ++i) {
        if (mode == TEE_OUTPUT_INDEX) {
            pyList.append(outPtr->data.u64Numbers[i]);
        } else if (mode == TEE_OUTPUT_STRING) {
            pyList.append(outPtr->data.strings[i].str);
        }
    }
}

void FeedKcalOutput(io::KcalOutput &kcalOutput, py::list &pyList)
{
    auto *outPtr = kcalOutput.Get();
    auto dataType = kcalOutput.Get()->dataType;
    for (size_t i = 0; i < outPtr->size; ++i) {
        if (dataType == MPC_STRING) {
            pyList.append(outPtr->data.strings[i].str);
        } else if (dataType == MPC_INT) {
            pyList.append(outPtr->data.u64Numbers[i]);
        } else if (dataType == MPC_DOUBLE) {
            pyList.append(outPtr->data.doubleNumbers[i]);
        }
    }
}

}  // namespace

class PyCallbackAdapter {
public:
    static int PySendCallback(const TeeNodeInfo &nodeInfo, const uint8_t *data, size_t dataLen,
                              const py::function &pySendFunc)
    {
        if (!data) {
            return 0;
        }
        try {
            py::dict nodeInfoDict;
            nodeInfoDict["nodeId"] = nodeInfo.nodeId;
            // zero-copy
            py::memoryview dataMview = py::memoryview::from_buffer(
                const_cast<uint8_t *>(data), {static_cast<py::ssize_t>(dataLen)}, {sizeof(uint8_t)});

            py::object result = pySendFunc(nodeInfoDict, dataMview);
            return result.cast<int>();
        } catch (const py::error_already_set &e) {
            py::print("Python send callback error:", e.what());
            return -1;
        } catch (const std::exception &e) {
            py::print("Send callback error:", e.what());
            return -1;
        }
    }

    static int PyRecvCallback(const TeeNodeInfo &nodeInfo, uint8_t *buffer, size_t maxLen,
                              const py::function &pyRecvFunc)
    {
        if (!buffer) {
            return 0;
        }
        try {
            py::dict nodeInfoDict;
            nodeInfoDict["nodeId"] = nodeInfo.nodeId;
            // zero-copy
            py::memoryview bufferMview =
                py::memoryview::from_buffer(buffer, {static_cast<py::ssize_t>(maxLen)}, {sizeof(uint8_t)}, false);

            py::object result = pyRecvFunc(nodeInfoDict, bufferMview);
            if (result.is_none()) {
                return -1;
            }
            return result.cast<int>();
        } catch (const py::error_already_set &e) {
            py::print("Python recv callback error:", e.what());
            return -1;
        } catch (const std::exception &e) {
            py::print("Recv callback error:", e.what());
            return -1;
        }
    }
};

void BindIoClasses(py::module_ &m)
{
    py::class_<io::KcalMpcShare>(m, "MpcShare")
        .def(py::init<>())
        .def(py::init<DG_MpcShare *>())
        .def_static("Create", &io::KcalMpcShare::Create, py::return_value_policy::take_ownership)
        .def("Set", &io::KcalMpcShare::Set)
        .def(
            "Get", [](io::KcalMpcShare &self) -> DG_MpcShare * { return self.Get(); },
            py::return_value_policy::reference)
        .def("Size", &io::KcalMpcShare::Size)
        .def("Type", &io::KcalMpcShare::Type);

    py::class_<io::KcalMpcShareSet>(m, "MpcShareSet")
        .def(py::init<>())
        .def_static(
            "Create", [](const std::vector<io::KcalMpcShare *> &shares) { return io::KcalMpcShareSet::Create(shares); },
            py::return_value_policy::take_ownership)
        .def(
            "Get", [](io::KcalMpcShareSet &self) -> DG_MpcShareSet * { return self.Get(); },
            py::return_value_policy::reference);
    py::class_<io::KcalInput>(m, "Input")
        .def(py::init<>())
        .def(py::init<DG_TeeInput *>())
        .def_static("Create", &io::KcalInput::Create, py::return_value_policy::take_ownership)
        .def("Set", &io::KcalInput::Set)
        .def("Get", &io::KcalInput::Get, py::return_value_policy::reference)
        .def("Fill", &io::KcalInput::Fill)
        .def("Size", &io::KcalInput::Size);
    // Alias of Input
    m.attr("Output") = m.attr("Input");
}

void BindOtherOperators(py::module_ &m)
{
    // PSI
    py::class_<Psi, OperatorBase, std::shared_ptr<Psi>>(m, "Psi")
        .def(py::init<>())
        .def("run", [](Psi &self, const py::list &input, py::list &output, DG_TeeMode mode) -> int {
            std::unique_ptr<io::KcalInput> kcalInput(io::KcalInput::Create());
            FeedKcalInput(input, kcalInput.get());
            io::KcalOutput kcalOutput;
            int ret = self.Run(kcalInput->Get(), kcalOutput.GetSecondaryPointer(), mode);
            FeedPsiOutput(kcalOutput, output, mode);
            return ret;
        });
    py::class_<Pir, OperatorBase, std::shared_ptr<Pir>>(m, "Pir")
        .def(py::init<>())
        .def("ServerPreProcess",
             [](Pir &self, const py::list &key, py::list &value) -> int {
                 std::unique_ptr<io::KcalPairList> kcalInput(io::KcalPairList::Create());
                 // build DG_PairList
                 FeedKcalPairList(key, value, kcalInput.get());
                 int ret = self.ServerPreProcess(kcalInput->Get());
                 return ret;
             })
        .def("ClientQuery",
             [](Pir &self, const py::list &input, py::list &output, DG_DummyMode mode) -> int {
                 std::unique_ptr<io::KcalInput> kcalInput(io::KcalInput::Create());
                 FeedKcalInput(input, kcalInput.get());
                 io::KcalOutput kcalOutput;
                 int ret = self.ClientQuery(kcalInput->Get(), kcalOutput.GetSecondaryPointer(), mode);
                 FeedKcalOutput(kcalOutput, output);
                 return ret;
             })
        .def("ServerAnswer", [](Pir &self) -> int {
            int ret = self.ServerAnswer();
            return ret;
        });
}

PYBIND11_MODULE(kcal, m)
{
    m.doc() = "KCAL Python bindings.";

    py::enum_<KCAL_AlgorithmsType>(m, "AlgorithmsType")
        .value("PSI", KCAL_AlgorithmsType::PSI)
        .value("PIR", KCAL_AlgorithmsType::PIR)
        .export_values();

    py::enum_<DG_TeeMode>(m, "TeeMode")
        .value("OUTPUT_INDEX", TEE_OUTPUT_INDEX)
        .value("OUTPUT_STRING", TEE_OUTPUT_STRING)
        .export_values();

    py::enum_<DG_DummyMode>(m, "DummyMode").value("NORMAL", NORMAL).value("DUMMY", DUMMY).export_values();

    py::enum_<DG_ShareType>(m, "ShareType")
        .value("FIX_POINT", FIX_POINT)
        .value("NON_FIX_POINT", NON_FIX_POINT)
        .export_values();

    py::class_<TeeNodeInfo>(m, "TeeNodeInfo").def(py::init<>()).def_readwrite("nodeId", &TeeNodeInfo::nodeId);

    py::class_<KCAL_Config>(m, "Config")
        .def(py::init<>())
        .def_readwrite("nodeId", &KCAL_Config::nodeId)
        .def_readwrite("fixBits", &KCAL_Config::fixBits)
        .def_readwrite("threadCount", &KCAL_Config::threadCount)
        .def_readwrite("worldSize", &KCAL_Config::worldSize)
        .def_readwrite("useSMAlg", &KCAL_Config::useSMAlg);

    py::class_<Context, std::shared_ptr<Context>> contextClass(m, "ContextBase");
    contextClass.def(py::init<>())
        .def("GetWorldSize", &Context::GetWorldSize)
        .def("NodeId", &Context::NodeId)
        .def("IsValid", &Context::IsValid)
        .def("GetConfig", &Context::GetConfig);

    py::class_<ContextExt, std::shared_ptr<ContextExt>>(m, "Context")
        .def(py::init<>())
        .def_static("create", [](KCAL_Config config, py::function sendCb, py::function recvCb) {
            auto cppSendCb = [sendCb](const TeeNodeInfo &nodeInfo, const uint8_t *data, size_t dataLen) {
                return PyCallbackAdapter::PySendCallback(nodeInfo, data, dataLen, sendCb);
            };

            auto cppRecvCb = [recvCb](const TeeNodeInfo &nodeInfo, uint8_t *buffer, size_t maxLen) {
                return PyCallbackAdapter::PyRecvCallback(nodeInfo, buffer, maxLen, recvCb);
            };

            return ContextExt::Create(config, cppSendCb, cppRecvCb);
        });

    BindIoClasses(m);

    py::class_<OperatorBase, std::shared_ptr<OperatorBase>>(m, "OperatorBase").def("GetType", &OperatorBase::GetType);

    BindOtherOperators(m);

    m.def("create_operator",
          [](const std::shared_ptr<ContextExt> &context, KCAL_AlgorithmsType type) -> std::shared_ptr<OperatorBase> {
              switch (type) {
                  case KCAL_AlgorithmsType::PSI:
                      return OperatorManager::CreateOperator<Psi>(context->GetKcalContext());
                  case KCAL_AlgorithmsType::PIR:
                      return OperatorManager::CreateOperator<Pir>(context->GetKcalContext());
                  default:
                      throw std::runtime_error("Unsupported operator type");
              }
          });

    m.def("is_op_registered", &OperatorManager::IsOperatorRegistered);

    m.def("register_all_ops", &RegisterAllOps);

    m.def("build_dg_string", [](const std::vector<std::string> &strings) -> py::object {
        DG_String *dg = nullptr;
        int ret = io::DataHelper::BuildDgString(strings, &dg);
        if (ret != 0) {
            throw std::runtime_error("BuildDgString failed");
        }
        ret = io::DataHelper::BuildDgString(strings, &dg);
        if (ret != 0) {
            throw std::runtime_error("BuildDgString failed");
        }
        return py::cast(dg);
    });

    m.def("release_output", [](DG_TeeOutput *output) { io::DataHelper::ReleaseOutput(&output); });

    m.def("release_mpc_share", [](DG_MpcShare *share) { io::DataHelper::ReleaseMpcShare(&share); });
}

}  // namespace kcal

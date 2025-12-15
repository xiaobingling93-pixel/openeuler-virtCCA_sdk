// Copyright (c) Huawei Technologies Co., Ltd. 2025-2025. All rights reserved.

#include "kcal_wrapper.h"

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include <memory>

#include "context_ext.h"

#include "kcal/core/operator_base.h"
#include "kcal/core/operator_manager.h"
#include "kcal/operator/all_operator_register.h"
#include "kcal/operator/kcal_arithmetic.h"
#include "kcal/operator/kcal_avg.h"
#include "kcal/operator/kcal_make_share.h"
#include "kcal/operator/kcal_maximum.h"
#include "kcal/operator/kcal_pir.h"
#include "kcal/operator/kcal_psi.h"
#include "kcal/operator/kcal_reveal_share.h"
#include "kcal/operator/kcal_sum.h"
#include "kcal/utils/io.h"

namespace py = pybind11;

namespace kcal {

namespace {

using PyShare = std::shared_ptr<io::KcalMpcShare>;

void FeedKcalInput(const py::list &pyList, io::KcalInput *kcalInput)
{
    if (pyList.empty()) {
        return;
    }
    const auto &itemTemp = pyList[0];
    if (py::isinstance<py::str>(itemTemp)) {
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
    } else {
        auto inData = std::make_unique<double[]>(pyList.size());
        for (size_t i = 0; i < pyList.size(); ++i) {
            if (py::isinstance<py::int_>(pyList[i]) || py::isinstance<py::float_>(pyList[i])) {
                inData[i] = pyList[i].cast<double>();
            } else {
                throw std::runtime_error("need number type");
            }
        }

        DG_TeeInput **internalInput = kcalInput->GetSecondaryPointer();
        (*internalInput)->data.doubleNumbers = inData.release();
        (*internalInput)->size = pyList.size();
        (*internalInput)->dataType = MPC_DOUBLE;
    }
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
    auto dataType = outPtr->dataType;
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

} // namespace

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
    py::class_<io::KcalMpcShare, PyShare>(m, "MpcShare")
        .def(py::init<>())
        .def(py::init<DG_MpcShare *>())
        .def("Set", &io::KcalMpcShare::Set)
        .def("Create", &io::KcalMpcShare::Create, py::return_value_policy::take_ownership)
        .def(
            "Get", [](io::KcalMpcShare &self) -> DG_MpcShare * { return self.Get(); },
            py::return_value_policy::reference)
        .def("Size", &io::KcalMpcShare::Size)
        .def("Type", &io::KcalMpcShare::Type);

    py::class_<io::KcalMpcShareSet>(m, "MpcShareSet")
        .def(py::init<>())
        .def(
            "Get", [](io::KcalMpcShareSet &self) -> DG_MpcShareSet * { return self.Get(); },
            py::return_value_policy::reference);
    py::class_<io::KcalInput>(m, "Input")
        .def(py::init<>())
        .def(py::init<DG_TeeInput *>())
        .def_static(
            "Create",
            []() -> std::shared_ptr<io::KcalInput> { return std::shared_ptr<io::KcalInput>(io::KcalInput::Create()); },
            py::return_value_policy::take_ownership)
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
            std::shared_ptr<io::KcalInput> kcalInput(io::KcalInput::Create());
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
                 std::shared_ptr<io::KcalPairList> kcalInput(io::KcalPairList::Create());
                 // build DG_PairList
                 FeedKcalPairList(key, value, kcalInput.get());
                 int ret = self.ServerPreProcess(kcalInput->Get());
                 return ret;
             })
        .def("ClientQuery",
             [](Pir &self, const py::list &input, py::list &output, DG_DummyMode mode) -> int {
                 std::shared_ptr<io::KcalInput> kcalInput(io::KcalInput::Create());
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

    // Arithmetic Operators
    py::class_<Arithmetic, OperatorBase, std::shared_ptr<Arithmetic>>(m, "Arithmetic").def(py::init<>());

    // Basic Arithmetic Operations
    py::class_<Add, Arithmetic, std::shared_ptr<Add>>(m, "Add")
        .def(py::init<>())
        .def("run", [](Add &self, const std::vector<PyShare> &shares, PyShare &outShare) -> int {
            auto ptr = outShare.get();
            return self.Run(io::KcalMpcShareSet(shares), ptr);
        });

    py::class_<Sub, Arithmetic, std::shared_ptr<Sub>>(m, "Sub")
        .def(py::init<>())
        .def("run", [](Sub &self, const std::vector<PyShare> &shares, PyShare &outShare) -> int {
            auto ptr = outShare.get();
            return self.Run(io::KcalMpcShareSet(shares), ptr);
        });

    py::class_<Mul, Arithmetic, std::shared_ptr<Mul>>(m, "Mul")
        .def(py::init<>())
        .def("run", [](Mul &self, const std::vector<PyShare> &shares, PyShare &outShare) -> int {
            auto ptr = outShare.get();
            return self.Run(io::KcalMpcShareSet(shares), ptr);
        });

    py::class_<Div, Arithmetic, std::shared_ptr<Div>>(m, "Div")
        .def(py::init<>())
        .def("run", [](Div &self, const std::vector<PyShare> &shares, PyShare &outShare) -> int {
            auto ptr = outShare.get();
            return self.Run(io::KcalMpcShareSet(shares), ptr);
        });

    // Comparison Operations
    py::class_<Less, Arithmetic, std::shared_ptr<Less>>(m, "Less")
        .def(py::init<>())
        .def("run", [](Less &self, const std::vector<PyShare> &shares, PyShare &outShare) -> int {
            auto ptr = outShare.get();
            return self.Run(io::KcalMpcShareSet(shares), ptr);
        });

    py::class_<LessEqual, Arithmetic, std::shared_ptr<LessEqual>>(m, "LessEqual")
        .def(py::init<>())
        .def("run", [](LessEqual &self, const std::vector<PyShare> &shares, PyShare &outShare) -> int {
            auto ptr = outShare.get();
            return self.Run(io::KcalMpcShareSet(shares), ptr);
        });

    py::class_<Greater, Arithmetic, std::shared_ptr<Greater>>(m, "Greater")
        .def(py::init<>())
        .def("run", [](Greater &self, const std::vector<PyShare> &shares, PyShare &outShare) -> int {
            auto ptr = outShare.get();
            return self.Run(io::KcalMpcShareSet(shares), ptr);
        });

    py::class_<GreaterEqual, Arithmetic, std::shared_ptr<GreaterEqual>>(m, "GreaterEqual")
        .def(py::init<>())
        .def("run", [](GreaterEqual &self, const std::vector<PyShare> &shares, PyShare &outShare) -> int {
            auto ptr = outShare.get();
            return self.Run(io::KcalMpcShareSet(shares), ptr);
        });

    py::class_<Equal, Arithmetic, std::shared_ptr<Equal>>(m, "Equal")
        .def(py::init<>())
        .def("run", [](Equal &self, const std::vector<PyShare> &shares, PyShare &outShare) -> int {
            auto ptr = outShare.get();
            return self.Run(io::KcalMpcShareSet(shares), ptr);
        });

    py::class_<NoEqual, Arithmetic, std::shared_ptr<NoEqual>>(m, "NoEqual")
        .def(py::init<>())
        .def("run", [](NoEqual &self, const std::vector<PyShare> &shares, PyShare &outShare) -> int {
            auto ptr = outShare.get();
            return self.Run(io::KcalMpcShareSet(shares), ptr);
        });

    // Aggregate Operations
    py::class_<Sum, Arithmetic, std::shared_ptr<Sum>>(m, "Sum")
        .def(py::init<>())
        .def("run", [](Sum &self, const std::vector<PyShare> &shares, PyShare &outShare) -> int {
            auto ptr = outShare.get();
            return self.Run(io::KcalMpcShareSet(shares), ptr);
        });

    py::class_<Avg, Arithmetic, std::shared_ptr<Avg>>(m, "Avg")
        .def(py::init<>())
        .def("run", [](Avg &self, const std::vector<PyShare> &shares, PyShare &outShare) -> int {
            auto ptr = outShare.get();
            return self.Run(io::KcalMpcShareSet(shares), ptr);
        });

    py::class_<Max, Arithmetic, std::shared_ptr<Max>>(m, "Max")
        .def(py::init<>())
        .def("run", [](Max &self, const std::vector<PyShare> &shares, PyShare &outShare) -> int {
            auto ptr = outShare.get();
            return self.Run(io::KcalMpcShareSet(shares), ptr);
        });

    py::class_<Min, Arithmetic, std::shared_ptr<Min>>(m, "Min")
        .def(py::init<>())
        .def("run", [](Min &self, const std::vector<PyShare> &shares, PyShare &outShare) -> int {
            auto ptr = outShare.get();
            return self.Run(io::KcalMpcShareSet(shares), ptr);
        });

    // Share Management
    py::class_<MakeShare, Arithmetic, std::shared_ptr<MakeShare>>(m, "MakeShare")
        .def(py::init<>())
        .def("run", [](MakeShare &self, const py::list &input, int isRecvShare, PyShare &share) -> int {
            io::KcalInput kcalInput(new DG_TeeInput());
            FeedKcalInput(input, &kcalInput);
            auto data = share.get(); // must have this
            return self.Run(kcalInput, isRecvShare, data);
        });

    py::class_<RevealShare, Arithmetic, std::shared_ptr<RevealShare>>(m, "RevealShare")
        .def(py::init<>())
        .def("run", [](RevealShare &self, const PyShare &share, py::list &output) -> int {
            io::KcalOutput kcalOutput;
            int ret = self.Run(share.get(), kcalOutput);
            FeedKcalOutput(kcalOutput, output);
            return ret;
        });
}

PYBIND11_MODULE(kcal, m)
{
    m.doc() = "KCAL Python bindings.";

    py::enum_<KCAL_AlgorithmsType>(m, "AlgorithmsType")
        .value("PSI", KCAL_AlgorithmsType::PSI)
        .value("PIR", KCAL_AlgorithmsType::PIR)
        .value("ARITHMETIC", KCAL_AlgorithmsType::ARITHMETIC)
        .value("MAKE_SHARE", KCAL_AlgorithmsType::MAKE_SHARE)
        .value("REVEAL_SHARE", KCAL_AlgorithmsType::REVEAL_SHARE)
        .value("ADD", KCAL_AlgorithmsType::ADD)
        .value("SUB", KCAL_AlgorithmsType::SUB)
        .value("MUL", KCAL_AlgorithmsType::MUL)
        .value("DIV", KCAL_AlgorithmsType::DIV)
        .value("LESS", KCAL_AlgorithmsType::LESS)
        .value("LESS_EQUAL", KCAL_AlgorithmsType::LESS_EQUAL)
        .value("GREATER", KCAL_AlgorithmsType::GREATER)
        .value("GREATER_EQUAL", KCAL_AlgorithmsType::GREATER_EQUAL)
        .value("EQUAL", KCAL_AlgorithmsType::EQUAL)
        .value("NO_EQUAL", KCAL_AlgorithmsType::NO_EQUAL)
        .value("SUM", KCAL_AlgorithmsType::SUM)
        .value("AVG", KCAL_AlgorithmsType::AVG)
        .value("MAX", KCAL_AlgorithmsType::MAX)
        .value("MIN", KCAL_AlgorithmsType::MIN)
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
                  case KCAL_AlgorithmsType::ARITHMETIC:
                      return OperatorManager::CreateOperator<Arithmetic>(context->GetKcalContext());
                  case KCAL_AlgorithmsType::MAKE_SHARE:
                      return OperatorManager::CreateOperator<MakeShare>(context->GetKcalContext());
                  case KCAL_AlgorithmsType::REVEAL_SHARE:
                      return OperatorManager::CreateOperator<RevealShare>(context->GetKcalContext());
                  case KCAL_AlgorithmsType::ADD:
                      return OperatorManager::CreateOperator<Add>(context->GetKcalContext());
                  case KCAL_AlgorithmsType::SUB:
                      return OperatorManager::CreateOperator<Sub>(context->GetKcalContext());
                  case KCAL_AlgorithmsType::MUL:
                      return OperatorManager::CreateOperator<Mul>(context->GetKcalContext());
                  case KCAL_AlgorithmsType::DIV:
                      return OperatorManager::CreateOperator<Div>(context->GetKcalContext());
                  case KCAL_AlgorithmsType::LESS:
                      return OperatorManager::CreateOperator<Less>(context->GetKcalContext());
                  case KCAL_AlgorithmsType::LESS_EQUAL:
                      return OperatorManager::CreateOperator<LessEqual>(context->GetKcalContext());
                  case KCAL_AlgorithmsType::GREATER:
                      return OperatorManager::CreateOperator<Greater>(context->GetKcalContext());
                  case KCAL_AlgorithmsType::GREATER_EQUAL:
                      return OperatorManager::CreateOperator<GreaterEqual>(context->GetKcalContext());
                  case KCAL_AlgorithmsType::EQUAL:
                      return OperatorManager::CreateOperator<Equal>(context->GetKcalContext());
                  case KCAL_AlgorithmsType::NO_EQUAL:
                      return OperatorManager::CreateOperator<NoEqual>(context->GetKcalContext());
                  case KCAL_AlgorithmsType::SUM:
                      return OperatorManager::CreateOperator<Sum>(context->GetKcalContext());
                  case KCAL_AlgorithmsType::AVG:
                      return OperatorManager::CreateOperator<Avg>(context->GetKcalContext());
                  case KCAL_AlgorithmsType::MAX:
                      return OperatorManager::CreateOperator<Max>(context->GetKcalContext());
                  case KCAL_AlgorithmsType::MIN:
                      return OperatorManager::CreateOperator<Min>(context->GetKcalContext());
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

} // namespace kcal

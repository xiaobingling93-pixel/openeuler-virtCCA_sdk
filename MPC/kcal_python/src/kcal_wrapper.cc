// Copyright (c) Huawei Technologies Co., Ltd. 2025-2025. All rights reserved.

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include <memory>

#include "context_ext.h"
#include "kcal/core/mpc_operator_base.h"
#include "kcal/core/operator_factory.h"
#include "kcal/operator/kcal_pir.h"
#include "kcal/operator/kcal_psi.h"
#include "kcal/utils/io.h"

namespace py = pybind11;

namespace kcal {

namespace {

void FeedKcalInput(const py::list &pyList, io::Input *kcalInput)
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

void FeedPsiOutput(io::Output &kcalOutput, py::list &pyList, DG_TeeMode mode)
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

void FeedKcalOutput(io::Output &kcalOutput, py::list &pyList)
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
    py::class_<io::MpcShare>(m, "MpcShare")
        .def(py::init<>())
        .def("size", &io::MpcShare::Size)
        .def("type", &io::MpcShare::Type);

    py::class_<io::MpcShareSet>(m, "MpcShareSet")
        .def(py::init<>())
        .def_static(
            "Create", [](const std::vector<io::MpcShare *> &shares) { return io::MpcShareSet::Create(shares); },
            py::return_value_policy::take_ownership)
        .def(
            "Get", [](io::MpcShareSet &self) -> DG_MpcShareSet * { return self.Get(); },
            py::return_value_policy::reference);

    py::class_<io::Input>(m, "Input")
        .def(py::init<>())
        .def(py::init<DG_TeeInput *>())
        .def(
            "create",
            [] {
                auto teeInput = std::make_unique<DG_TeeInput>();
                auto input = std::make_unique<io::Input>(teeInput.release());
                return input;
            },
            py::return_value_policy::take_ownership)
        .def("Set", &io::Input::Set)
        .def("Fill", &io::Input::Fill)
        .def("Size", &io::Input::Size);

    // Alias of Input
    m.attr("Output") = m.attr("Input");
}

void BindOtherOperators(py::module_ &m)
{
    // PSI
    py::class_<Psi, std::shared_ptr<Psi>>(m, "Psi")
        .def(py::init<std::shared_ptr<Context>>())
        .def("run", [](Psi &self, const py::list &input, py::list &output, DG_TeeMode mode) -> int {
            io::Input kcalInput(new DG_TeeInput());
            FeedKcalInput(input, &kcalInput);
            io::Output kcalOutput;
            int ret = self.Run(kcalInput, kcalOutput, mode);
            FeedPsiOutput(kcalOutput, output, mode);
            return ret;
        });

    py::class_<Pir, std::shared_ptr<Pir>>(m, "Pir")
        .def(py::init<std::shared_ptr<Context>>())
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
                 io::Input kcalInput(new DG_TeeInput());
                 FeedKcalInput(input, &kcalInput);
                 io::Output kcalOutput;
                 int ret = self.ClientQuery(kcalInput, kcalOutput, mode);
                 FeedKcalOutput(kcalOutput, output);
                 return ret;
             })
        .def("ServerAnswer", [](Pir &self) -> int {
            int ret = self.ServerAnswer();
            return ret;
        });
}

void BindMpcOperators(py::module_ &m)
{
    py::class_<MpcOperatorBase, std::shared_ptr<MpcOperatorBase>>(m, "OperatorBase")
        .def("GetType", &MpcOperatorBase::GetType)
        .def("run",
             [](MpcOperatorBase &self, const std::vector<io::MpcShare *> &shares, io::MpcShare *outShare) -> int {
                 auto shareSetPtr = io::MpcShareSet::Create(shares);
                 return self.Run(shareSetPtr, outShare);
             });

    py::class_<MakeShare, std::shared_ptr<MakeShare>>(m, "MakeShare")
        .def(py::init<std::shared_ptr<Context>>())
        .def("run", [](MakeShare &self, const py::list &input, int isRecvShare, io::MpcShare &share) {
            io::Input kcalInput(new DG_TeeInput());
            FeedKcalInput(input, &kcalInput);
            return self.Run(kcalInput, isRecvShare, &share);
        });

    py::class_<RevealShare, std::shared_ptr<RevealShare>>(m, "RevealShare")
        .def(py::init<std::shared_ptr<Context>>())
        .def("run", [](RevealShare &self, const io::MpcShare &share, py::list &output) {
            io::Output out;
            int ret = self.Run(&share, out);
            FeedKcalOutput(out, output);
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

    py::class_<Config>(m, "Config")
        .def(py::init<>())
        .def_readwrite("nodeId", &Config::nodeId)
        .def_readwrite("fixBits", &Config::fixBits)
        .def_readwrite("threadCount", &Config::threadCount)
        .def_readwrite("worldSize", &Config::worldSize)
        .def_readwrite("useSMAlg", &Config::useSMAlg);

    py::class_<ContextExt, std::shared_ptr<ContextExt>>(m, "Context")
        .def(py::init<>())
        .def_static("create", [](Config config, py::function sendCb, py::function recvCb) {
            auto cppSendCb = [sendCb](const TeeNodeInfo &nodeInfo, const uint8_t *data, size_t dataLen) {
                return PyCallbackAdapter::PySendCallback(nodeInfo, data, dataLen, sendCb);
            };

            auto cppRecvCb = [recvCb](const TeeNodeInfo &nodeInfo, uint8_t *buffer, size_t maxLen) {
                return PyCallbackAdapter::PyRecvCallback(nodeInfo, buffer, maxLen, recvCb);
            };

            return ContextExt::Create(config, cppSendCb, cppRecvCb);
        });

    BindIoClasses(m);

    BindMpcOperators(m);

    m.def("create_psi", [](const std::shared_ptr<ContextExt> &context) -> std::shared_ptr<Psi> {
        return OperatorFactory::CreatePsi(context->GetKcalContext());
    });

    m.def("create_pir", [](const std::shared_ptr<ContextExt> &context) -> std::shared_ptr<Pir> {
        return OperatorFactory::CreatePir(context->GetKcalContext());
    });

    BindOtherOperators(m);

    m.def("create_make_share", [](const std::shared_ptr<ContextExt> &context) -> std::shared_ptr<MakeShare> {
        return OperatorFactory::CreateMakeShare(context->GetKcalContext());
    });

    m.def("create_reveal_share", [](const std::shared_ptr<ContextExt> &context) -> std::shared_ptr<RevealShare> {
        return OperatorFactory::CreateRevealShare(context->GetKcalContext());
    });

    m.def("create_mpc",
          [](const std::shared_ptr<ContextExt> &context, KCAL_AlgorithmsType type) -> std::shared_ptr<MpcOperatorBase> {
              return OperatorFactory::CreateMpc(context->GetKcalContext(), type);
          });
}

} // namespace kcal

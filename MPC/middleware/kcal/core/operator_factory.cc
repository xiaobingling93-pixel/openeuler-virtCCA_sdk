/*
 * Copyright (c) Huawei Technologies Co., Ltd. 2024. All rights reserved.
 * virtCCA_sdk is licensed under the Mulan PSL v2.
 * You can use this software according to the terms and conditions of the Mulan PSL v2.
 * You may obtain a copy of Mulan PSL v2 at:
 *     http://license.coscl.org.cn/MulanPSL2
 * THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND, EITHER EXPRESS OR
 * IMPLIED, INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT, MERCHANTABILITY OR FIT FOR A PARTICULAR
 * PURPOSE.
 * See the Mulan PSL v2 for more details.
 */

#include "kcal/core/operator_factory.h"
#include "kcal/core/operator_registry.h"

namespace kcal {

std::unique_ptr<Psi> OperatorFactory::CreatePsi(std::shared_ptr<Context> context)
{
    return Psi::Create(std::move(context));
}

std::unique_ptr<Pir> OperatorFactory::CreatePir(std::shared_ptr<Context> context)
{
    return Pir::Create(std::move(context));
}

std::unique_ptr<MakeShare> OperatorFactory::CreateMakeShare(std::shared_ptr<Context> context)
{
    return MakeShare::Create(std::move(context));
}

std::unique_ptr<RevealShare> OperatorFactory::CreateRevealShare(std::shared_ptr<Context> context)
{
    return RevealShare::Create(std::move(context));
}

std::shared_ptr<MpcOperatorBase> OperatorFactory::CreateMpc(std::shared_ptr<Context> context, KCAL_AlgorithmsType type)
{
    if (!context || !context->IsValid()) {
        return nullptr;
    }
    auto op = OperatorRegistry::Instance().CreateOperator(type);
    if (!op) {
        return nullptr;
    }
    int ret = op->Initialize(std::move(context));
    if (ret != DG_SUCCESS) {
        return nullptr;
    }

    return op;
}

} // namespace kcal
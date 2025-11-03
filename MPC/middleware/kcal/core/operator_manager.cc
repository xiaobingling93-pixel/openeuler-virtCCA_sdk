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

#include "kcal/core/operator_manager.h"
#include "kcal/core/operator_registry.h"

namespace kcal {

std::shared_ptr<OperatorBase> OperatorManager::CreateOperator(std::shared_ptr<Context> context,
                                                              KCAL_AlgorithmsType type)
{
    if (!context || !context->IsValid()) {
        return nullptr;
    }

    auto op = OperatorRegistry::Instance().CreateOperator(type);
    if (!op) {
        return nullptr;
    }

    int rv = op->Initialize(context);
    if (rv != DG_SUCCESS) {
        return nullptr;
    }

    return op;
}

std::shared_ptr<OperatorBase> OperatorManager::CreateOperatorWithConfig(KCAL_Config config,
                                                                        TEE_NET_RES *netRes,
                                                                        KCAL_AlgorithmsType type)
{
    auto context = Context::Create(config, netRes);
    if (!context) {
        return nullptr;
    }
    return CreateOperator(context, type);
}

std::unordered_map<KCAL_AlgorithmsType, std::shared_ptr<OperatorBase>> OperatorManager::CreateOperators(
    std::shared_ptr<Context> context,
    const std::vector<KCAL_AlgorithmsType> &types)
{
    std::unordered_map<KCAL_AlgorithmsType, std::shared_ptr<OperatorBase>> operators;
    for (auto type : types) {
        auto op = CreateOperator(context, type);
        if (op) {
            operators[type] = op;
        }
    }
    return operators;
}

bool OperatorManager::IsOperatorRegistered(KCAL_AlgorithmsType type)
{
    return OperatorRegistry::Instance().IsOperatorInitialized(type);
}

} // namespace kcal
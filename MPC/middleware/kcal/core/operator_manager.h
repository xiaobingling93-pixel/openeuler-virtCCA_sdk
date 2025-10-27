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

#ifndef OPERATOR_MANAGER_H
#define OPERATOR_MANAGER_H

#include <memory>
#include "kcal/core/operator_base.h"

namespace kcal {

class OperatorManager {
public:
    OperatorManager() = delete;
    ~OperatorManager() = delete;

    static std::shared_ptr<OperatorBase> CreateOperator(std::shared_ptr<Context> context,
                                                        KCAL_AlgorithmsType type);

    template <typename OperatorType>
    static std::shared_ptr<OperatorType> CreateOperator(std::shared_ptr<Context> context);

    static std::shared_ptr<OperatorBase>
    CreateOperatorWithConfig(KCAL_Config config, TEE_NET_RES *netRes, KCAL_AlgorithmsType type);

    static std::unordered_map<KCAL_AlgorithmsType, std::shared_ptr<OperatorBase>>
    CreateOperators(std::shared_ptr<Context> context,
                    const std::vector<KCAL_AlgorithmsType> &types);

    static bool IsOperatorRegistered(KCAL_AlgorithmsType type);
};

template <typename OperatorType>
std::shared_ptr<OperatorType> OperatorManager::CreateOperator(std::shared_ptr<Context> context)
{
    static_assert(std::is_base_of_v<OperatorBase, OperatorType>,
                  "OperatorType must derive from OperatorBase");
    auto baseOp = CreateOperator(context, OperatorType{}.GetType());
    return std::static_pointer_cast<OperatorType>(baseOp); // compile-time type check
}

} // namespace kcal

#endif // OPERATOR_MANAGER_H
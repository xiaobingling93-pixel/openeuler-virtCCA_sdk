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

#ifndef OPERATOR_REGISTRY_H
#define OPERATOR_REGISTRY_H

#include <memory>
#include <unordered_map>
#include <functional>
#include <mutex>
#include "kcal/core/operator_base.h"
#include "kcal/enumeration/kcal_enum.h"

namespace kcal {

class OperatorRegistry {
public:
    static OperatorRegistry &Instance();

    template <typename OperatorType> void RegisterOperator(KCAL_AlgorithmsType type);

    std::unique_ptr<OperatorBase> CreateOperator(KCAL_AlgorithmsType type);
    bool IsOperatorInitialized(KCAL_AlgorithmsType type) const;

private:
    OperatorRegistry() = default;
    ~OperatorRegistry() = default;

    using OperatorFactory = std::function<std::unique_ptr<OperatorBase>()>;
    std::unordered_map<KCAL_AlgorithmsType, OperatorFactory> factories_;
    mutable std::mutex mutex_;
};

template <typename OperatorType> void OperatorRegistry::RegisterOperator(KCAL_AlgorithmsType type)
{
    static_assert(std::is_base_of_v<OperatorBase, OperatorType>,
                  "OperatorType must derive from OperatorBase");

    std::lock_guard<std::mutex> lock(mutex_);
    factories_[type] = []() -> std::unique_ptr<OperatorBase> {
        return std::make_unique<OperatorType>();
    };
}

} // namespace kcal

#endif // OPERATOR_REGISTRY_H
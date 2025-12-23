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

#include "kcal/core/operator_registry.h"

namespace kcal {

OperatorRegistry &OperatorRegistry::Instance()
{
    static OperatorRegistry instance;
    return instance;
}

std::unique_ptr<MpcOperatorBase> OperatorRegistry::CreateOperator(KCAL_AlgorithmsType type)
{
    std::lock_guard<std::mutex> lock(mutex_);

    auto it = factories_.find(type);
    if (it == factories_.end()) {
        return nullptr;
    }
    return it->second();
}

bool OperatorRegistry::IsOperatorInitialized(KCAL_AlgorithmsType type) const
{
    std::lock_guard<std::mutex> lock(mutex_);
    return factories_.find(type) != factories_.end();
}

} // namespace kcal
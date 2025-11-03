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

#ifndef OPERATOR_BASE_H
#define OPERATOR_BASE_H

#include <memory>
#include "kcal/core/context.h"
#include "kcal/enumeration/kcal_enum.h"

namespace kcal {

class OperatorBase {
public:
    virtual ~OperatorBase() = default;

    int Initialize(std::shared_ptr<Context> context);
    virtual KCAL_AlgorithmsType GetType() const = 0;

    bool IsInitialized() const { return initialized_; }

protected:
    OperatorBase() = default;

    virtual int GetTeeCtx(const std::shared_ptr<Context> &context) = 0;

    bool initialized_ = false;
    std::shared_ptr<Context> context_;
};

} // namespace kcal

#endif // OPERATOR_BASE_H
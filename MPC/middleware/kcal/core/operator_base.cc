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

#include "kcal/core/operator_base.h"

namespace kcal {

int OperatorBase::Initialize(std::shared_ptr<Context> context)
{
    if (!context || !context->IsValid()) {
        return DG_ERR_MPC_INVALID_PARAM;
    }
    if (initialized_) {
        return DG_SUCCESS;
    }
    int ret = GetTeeCtx(context);
    if (ret != DG_SUCCESS) {
        return DG_FAILURE;
    }
    context_ = context;
    initialized_ = true;
    return DG_SUCCESS;
}

} // namespace kcal

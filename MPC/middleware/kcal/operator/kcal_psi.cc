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

#include "kcal/operator/kcal_psi.h"
#include "kcal/utils/node_info_helper.h"

namespace kcal {

Psi::Psi()
{
    opts_ = std::make_unique<DG_PrivateSet_Opts>();
    *opts_ = DG_InitPsiOpts();
}

Psi::~Psi() { opts_->releaseTeeCtx(&dgTeeCtx_); }

int Psi::Init(std::shared_ptr<Context> ctx)
{
    if (!ctx) {
        return DG_ERR_MPC_INVALID_PARAM;
    }

    auto nodeInfoHelper = utils::NodeInfoHelper::Create(ctx->GetWorldSize());
    if (!nodeInfoHelper) {
        return DG_ERR_MPC_INVALID_PARAM;
    }

    int rv = opts_->initTeeCtx(ctx->GetTeeConfig(), &dgTeeCtx_);
    if (rv != 0) {
        return rv;
    }

    rv = opts_->setTeeNodeInfos(dgTeeCtx_, nodeInfoHelper->Get());
    if (rv != 0) {
        return rv;
    }

    baseCtx_ = std::move(ctx);

    return DG_SUCCESS;
}

int Psi::Run(DG_TeeInput *input, DG_TeeOutput **output, DG_TeeMode outputMode)
{
    if (!input || !output) {
        return DG_ERR_MPC_INVALID_PARAM;
    }
    return opts_->calculate(dgTeeCtx_, PSI, input, output, outputMode);
}

}

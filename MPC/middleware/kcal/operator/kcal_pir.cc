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

#include "kcal/operator/kcal_pir.h"
#include "kcal/utils/node_info_helper.h"

namespace kcal {

Pir::Pir()
{
    opts_ = std::make_unique<DG_PIR_Opts>();
    *opts_ = DG_InitPirOpts();
}

Pir::~Pir()
{
    opts_->releaseBucketMap(&bucketMap_);
    opts_->releaseTeeCtx(&dgTeeCtx_);
}

int Pir::Init(std::shared_ptr<Context> ctx)
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

int Pir::ServerPreProcess(DG_PairList *pairList)
{
    if (!pairList) {
        return DG_ERR_MPC_INVALID_PARAM;
    }
    return opts_->offlineCalculate(dgTeeCtx_, pairList, &bucketMap_);
}

int Pir::ClientQuery(DG_TeeInput *input, DG_TeeOutput **output, DG_DummyMode dummyMode)
{
    if (!input || !output) {
        return DG_ERR_MPC_INVALID_PARAM;
    }
    return opts_->clientCalculate(dgTeeCtx_, dummyMode, input, output);
}

int Pir::ServerAnswer()
{
    return opts_->serverCalculate(dgTeeCtx_, bucketMap_);
}

}

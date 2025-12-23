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

std::unique_ptr<Pir> Pir::Create(std::shared_ptr<Context> context)
{
    auto op = std::make_unique<Pir>(std::move(context));

    op->opts_ = std::make_unique<DG_PIR_Opts>();
    *op->opts_ = DG_InitPirOpts();

    int ret = op->Initialize();
    if (ret != 0) {
        return nullptr;
    }

    return op;
}

int Pir::Initialize()
{
    if (!context_ || !context_->IsValid()) {
        return DG_ERR_MPC_INVALID_PARAM;
    }

    dgTeeCtx_ = context_->GetTeeCtx(KCAL_AlgorithmsType::PIR);
    if (!dgTeeCtx_) {
        return DG_ERR_MPC_INVALID_PARAM;
    }

    initialized_ = true;
    return DG_SUCCESS;
}

Pir::~Pir()
{
    if (initialized_) {
        opts_->releaseBucketMap(&bucketMap_);
        dgTeeCtx_ = nullptr;
        context_.reset();
        initialized_ = false;
    }
}

int Pir::ServerPreProcess(DG_PairList *pairList)
{
    if (!initialized_ || !dgTeeCtx_) {
        return DG_ERR_MPC_INVALID_PARAM;
    }
    if (!pairList) {
        return DG_ERR_MPC_INVALID_PARAM;
    }
    return opts_->offlineCalculate(dgTeeCtx_, pairList, &bucketMap_);
}

int Pir::ClientQuery(const io::Input &input, io::Output &output, DG_DummyMode dummyMode)
{
    if (!initialized_ || !dgTeeCtx_) {
        return DG_ERR_MPC_INVALID_PARAM;
    }
    if (!input.Valid()) {
        return DG_ERR_MPC_INVALID_PARAM;
    }
    DG_TeeOutput *rawOutput = nullptr;
    int ret = opts_->clientCalculate(dgTeeCtx_, dummyMode, input.Get(), &rawOutput);
    if (ret == DG_SUCCESS) {
        output.Reset(rawOutput);
    }
    return ret;
}

int Pir::ServerAnswer()
{
    if (!initialized_ || !dgTeeCtx_) {
        return DG_ERR_MPC_INVALID_PARAM;
    }
    return opts_->serverCalculate(dgTeeCtx_, bucketMap_);
}

} // namespace kcal

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

#include "kcal/core/context.h"
#include "kcal/operator/mpc_operator_register.h"

namespace kcal {

Context::Context(Config config) : config_(config) { teeCtxManager_ = std::make_unique<TeeCtxManager>(); }

Context::~Context()
{
    DG_ReleaseConfig(&teeCfg_);
    DG_ReleaseConfigOpts(&cfgOpts_);
}

int Context::Init()
{
    int rv = DG_InitConfigOpts(MPC, &cfgOpts_);
    if (rv != DG_SUCCESS) {
        return rv;
    }
    rv = cfgOpts_->init(&teeCfg_);
    if (rv != DG_SUCCESS) {
        return rv;
    }

    rv = cfgOpts_->setIntValue(teeCfg_, DG_CON_MPC_TEE_INT_NODEID, config_.nodeId);
    if (rv != DG_SUCCESS) {
        return rv;
    }

    rv = cfgOpts_->setIntValue(teeCfg_, DG_CON_MPC_TEE_INT_FXP_BITS, config_.fixBits);
    if (rv != DG_SUCCESS) {
        return rv;
    }
    rv = cfgOpts_->setIntValue(teeCfg_, DG_CON_MPC_TEE_INT_THREAD_COUNT, config_.threadCount);
    if (rv != DG_SUCCESS) {
        return rv;
    }
    // NOTE: kcal_25.0.7.2 version does not support SM cryptographic algorithms
    // DG_CON_MPC_TEE_INT_IS_SM_ALGORITHM parameter cannot be set, need delete below 'if-else' code
    if (config_.useSMAlg) {
        rv = cfgOpts_->setIntValue(teeCfg_, DG_CON_MPC_TEE_INT_IS_SM_ALGORITHM, 1);
    } else {
        rv = cfgOpts_->setIntValue(teeCfg_, DG_CON_MPC_TEE_INT_IS_SM_ALGORITHM, 0);
    }
    if (rv != DG_SUCCESS) {
        return rv;
    }

    return DG_SUCCESS;
}

DG_TeeCtx *Context::GetTeeCtx(KCAL_AlgorithmsType algoType)
{
    if (!teeCtxManager_ || !teeCfg_) {
        return nullptr;
    }
    return teeCtxManager_->GetTeeCtx(algoType, teeCfg_, config_.worldSize);
}

bool Context::IsTeeCtxInitialized(KCAL_AlgorithmsType algoType) const
{
    if (!teeCtxManager_) {
        return false;
    }
    return teeCtxManager_->IsTeeCtxInitialized(algoType);
}

std::shared_ptr<Context> Context::Create(Config config, TEE_NET_RES *netRes)
{
    if (!netRes) {
        return nullptr;
    }
    auto context = std::make_shared<Context>(config);
    int rv = context->Init();
    if (rv != DG_SUCCESS) {
        return nullptr;
    }
    rv = context->SetNetRes(netRes);
    if (rv != DG_SUCCESS) {
        return nullptr;
    }
    RegisterAllOps();
    return context;
}

int Context::SetNetRes(TEE_NET_RES *teeNetRes)
{
    DG_Void netFunc = {.data = teeNetRes, .size = sizeof(TEE_NET_RES)};
    return cfgOpts_->setVoidValue(teeCfg_, DG_CON_MPC_TEE_VOID_NET_API, &netFunc);
}

} // namespace kcal
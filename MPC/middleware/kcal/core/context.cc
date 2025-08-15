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

namespace kcal {

Context::Context(KCAL_Config config, KCAL_AlgorithmsType type) : config_(config), type_(type) {}

Context::~Context()
{
    DG_ReleaseConfig(&teeCfg_);
    DG_ReleaseConfigOpts(&cfgOpts_);
}

int Context::Init()
{
    int rv = DG_InitConfigOpts(DG_BusinessType::MPC, &cfgOpts_);
    if (rv != DG_SUCCESS) {
        return rv;
    }
    rv = cfgOpts_->init(&teeCfg_);
    if (rv != DG_SUCCESS) {
        return rv;
    }

    cfgOpts_->setIntValue(teeCfg_, DG_CON_MPC_TEE_INT_NODEID, config_.nodeId);
    if (type_ == KCAL_AlgorithmsType::PSI || type_ == KCAL_AlgorithmsType::PIR) {
        cfgOpts_->setIntValue(teeCfg_, DG_CON_MPC_TEE_INT_FXP_BITS, 0);
    } else {
        cfgOpts_->setIntValue(teeCfg_, DG_CON_MPC_TEE_INT_FXP_BITS, config_.fixBits);
    }
    cfgOpts_->setIntValue(teeCfg_, DG_CON_MPC_TEE_INT_THREAD_COUNT, config_.threadCount);
    if (config_.useSMAlg) {
        cfgOpts_->setIntValue(teeCfg_, DG_CON_MPC_TEE_INT_IS_SM_ALGORITHM, 1);
    } else {
        cfgOpts_->setIntValue(teeCfg_, DG_CON_MPC_TEE_INT_IS_SM_ALGORITHM, 0);
    }

    return DG_SUCCESS;
}

std::shared_ptr<Context> Context::Create(KCAL_Config config, TEE_NET_RES *netRes, KCAL_AlgorithmsType type)
{
    auto context = std::make_shared<Context>(config, type);
    context->Init();
    context->SetNetRes(netRes);
    return context;
}

void Context::SetNetRes(TEE_NET_RES *teeNetRes)
{
    DG_Void netFunc = {.data = teeNetRes, .size = sizeof(TEE_NET_RES)};
    cfgOpts_->setVoidValue(teeCfg_, DG_CON_MPC_TEE_VOID_NET_API, &netFunc);
}

}

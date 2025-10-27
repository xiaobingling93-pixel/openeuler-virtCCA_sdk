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

#include "kcal/core/pir_initializer.h"
#include "kcal/utils/node_info_helper.h"

namespace kcal {

PirInitializer::PirInitializer() : opts_(DG_InitPirOpts()) {}

int PirInitializer::InitializeTeeCtx(void *teeConfig, int worldSize, DG_TeeCtx **teeCtx)
{
    auto nodeInfoHelper = utils::NodeInfoHelper::Create(worldSize);
    if (!nodeInfoHelper) {
        return DG_ERR_MPC_INVALID_PARAM;
    }
    int rv = opts_.initTeeCtx(teeConfig, teeCtx);
    if (rv != DG_SUCCESS) {
        return rv;
    }
    rv = opts_.setTeeNodeInfos(*teeCtx, nodeInfoHelper->Get());
    if (rv != DG_SUCCESS) {
        return rv;
    }
    return DG_SUCCESS;
}

void PirInitializer::ReleaseTeeCtx(DG_TeeCtx **teeCtx)
{
    if (teeCtx && *teeCtx) {
        opts_.releaseTeeCtx(teeCtx);
    }
}

} // namespace kcal
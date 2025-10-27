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

#ifndef TEE_CTX_INITIALIZER_H
#define TEE_CTX_INITIALIZER_H

#include "kcal/api/kcal_api.h"
#include "kcal/enumeration/kcal_enum.h"

namespace kcal {

class TeeCtxInitializer {
public:
    virtual ~TeeCtxInitializer() = default;

    virtual KCAL_AlgorithmsType GetAlgorithmType() const = 0;
    virtual int InitializeTeeCtx(void *teeConfig, int worldSize, DG_TeeCtx **teeCtx) = 0;
    virtual void ReleaseTeeCtx(DG_TeeCtx **teeCtx) = 0;
    virtual bool SupportsAlgorithm(KCAL_AlgorithmsType algoType) const = 0;
};

} // namespace kcal

#endif // TEE_CTX_INITIALIZER_H
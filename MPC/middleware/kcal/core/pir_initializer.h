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

#ifndef PIR_INITIALIZER_H
#define PIR_INITIALIZER_H

#include "kcal/core/tee_ctx_initializer.h"

namespace kcal {

class PirInitializer : public TeeCtxInitializer {
public:
    PirInitializer();
    ~PirInitializer() override = default;

    KCAL_AlgorithmsType GetAlgorithmType() const override { return KCAL_AlgorithmsType::PIR; }

    int InitializeTeeCtx(void *teeConfig, int worldSize, DG_TeeCtx **teeCtx) override;
    void ReleaseTeeCtx(DG_TeeCtx **teeCtx) override;

    bool SupportsAlgorithm(KCAL_AlgorithmsType algoType) const override { return algoType == KCAL_AlgorithmsType::PIR; }

private:
    DG_PIR_Opts opts_;
};

} // namespace kcal

#endif // PIR_INITIALIZER_H
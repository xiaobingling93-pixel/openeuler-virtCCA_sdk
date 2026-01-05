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

#ifndef TEE_CTX_MANAGER_H
#define TEE_CTX_MANAGER_H

#include <unordered_map>
#include <memory>
#include <mutex>
#include <vector>
#include "kcal/core/tee_ctx_initializer.h"
#include "kcal/api/kcal_api.h"
#include "kcal/enumeration/kcal_enum.h"

namespace kcal {

class TeeCtxManager {
public:
    TeeCtxManager();
    ~TeeCtxManager();

    DG_TeeCtx *GetTeeCtx(KCAL_AlgorithmsType type, void *teeConfig, int worldSize);
    bool IsTeeCtxInitialized(KCAL_AlgorithmsType algoType) const;

    void RegisterInitializer(std::unique_ptr<TeeCtxInitializer> initializer);
    void RegisterInitializers(std::vector<std::unique_ptr<TeeCtxInitializer>> initializers);
    bool SupportAlgorithm(KCAL_AlgorithmsType algoType) const;

    void Cleanup();

private:
    TeeCtxInitializer *FindInitializer(KCAL_AlgorithmsType algoType) const;

    std::unordered_map<KCAL_AlgorithmsType, DG_TeeCtx *> teeCtxMap_;
    std::vector<std::unique_ptr<TeeCtxInitializer>> initializers_;
    mutable std::mutex mutex_;
};

} // namespace kcal

#endif // TEE_CTX_MANAGER_H
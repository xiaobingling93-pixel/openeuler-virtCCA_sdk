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

#include "kcal/core/tee_ctx_manager.h"
#include "kcal/core/psi_initializer.h"
#include "kcal/core/pir_initializer.h"
#include "kcal/core/arithmetic_initializer.h"

namespace kcal {

namespace {

KCAL_AlgorithmsType AlgoTypeTransfer(KCAL_AlgorithmsType type)
{
    switch (type) {
        case KCAL_AlgorithmsType::PSI:
        case KCAL_AlgorithmsType::PIR:
            return type;
        default:
            return KCAL_AlgorithmsType::ARITHMETIC;
    }
}

} // namespace

TeeCtxManager::TeeCtxManager()
{
    RegisterInitializer(std::make_unique<PsiInitializer>());
    RegisterInitializer(std::make_unique<PirInitializer>());
    RegisterInitializer(std::make_unique<ArithmeticInitializer>());
}

TeeCtxManager::~TeeCtxManager() { Cleanup(); }

DG_TeeCtx *TeeCtxManager::GetTeeCtx(KCAL_AlgorithmsType type, void *teeConfig, int worldSize)
{
    type = AlgoTypeTransfer(type);

    std::lock_guard<std::mutex> lock(mutex_);
    auto it = teeCtxMap_.find(type);
    if (it != teeCtxMap_.end() && it->second != nullptr) {
        return it->second;
    }

    auto *initializer = FindInitializer(type);
    if (!initializer) {
        return nullptr;
    }

    DG_TeeCtx *teeCtx = nullptr;
    int rv = initializer->InitializeTeeCtx(teeConfig, worldSize, &teeCtx);
    if (rv != DG_SUCCESS) {
        return nullptr;
    }

    teeCtxMap_[type] = teeCtx;
    return teeCtx;
}

bool TeeCtxManager::IsTeeCtxInitialized(KCAL_AlgorithmsType algoType) const
{
    std::lock_guard<std::mutex> lock(mutex_);
    auto it = teeCtxMap_.find(algoType);
    return it != teeCtxMap_.end() && it->second != nullptr;
}

void TeeCtxManager::RegisterInitializer(std::unique_ptr<TeeCtxInitializer> initializer)
{
    std::lock_guard<std::mutex> lock(mutex_);
    if (initializer) {
        initializers_.push_back(std::move(initializer));
    }
}

void TeeCtxManager::RegisterInitializers(std::vector<std::unique_ptr<TeeCtxInitializer>> initializers)
{
    std::lock_guard<std::mutex> lock(mutex_);
    for (auto &initializer : initializers) {
        if (initializer) {
            initializers_.push_back(std::move(initializer));
        }
    }
}

bool TeeCtxManager::SupportAlgorithm(KCAL_AlgorithmsType algoType) const
{
    std::lock_guard<std::mutex> lock(mutex_);
    return FindInitializer(algoType) != nullptr;
}

TeeCtxInitializer *TeeCtxManager::FindInitializer(KCAL_AlgorithmsType algoType) const
{
    for (const auto &initializer : initializers_) {
        if (initializer->SupportsAlgorithm(algoType)) {
            return initializer.get();
        }
    }
    return nullptr;
}

void TeeCtxManager::Cleanup()
{
    std::lock_guard<std::mutex> lock(mutex_);
    for (auto &[algoType, teeCtx] : teeCtxMap_) {
        if (teeCtx) {
            if (auto *initializer = FindInitializer(algoType)) {
                initializer->ReleaseTeeCtx(&teeCtx);
            }
        }
    }
    teeCtxMap_.clear();
}

} // namespace kcal
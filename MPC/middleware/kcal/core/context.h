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

#ifndef CONTEXT_H
#define CONTEXT_H

#include <memory>
#include "kcal/api/kcal_api.h"
#include "kcal/enumeration/kcal_enum.h"
#include "kcal/core/tee_ctx_manager.h"

namespace kcal {

struct Config {
    int nodeId;
    int fixBits;
    int threadCount;
    int worldSize;
    bool useSMAlg;
};

class Context {
public:
    Context() = default;
    explicit Context(Config config);
    ~Context();

    Context(const Context &) = delete;
    Context &operator=(const Context &) = delete;

    static std::shared_ptr<Context> Create(Config config, TEE_NET_RES *netRes);
    int Init();

    int GetWorldSize() const { return config_.worldSize; }
    void *GetTeeConfig() { return teeCfg_; }
    bool IsValid() const { return teeCfg_ != nullptr; }
    Config GetConfig() const { return config_; }
    int NodeId() const { return config_.nodeId; }

    DG_TeeCtx *GetTeeCtx(KCAL_AlgorithmsType algoType);
    bool IsTeeCtxInitialized(KCAL_AlgorithmsType algoType) const;

private:
    int SetNetRes(TEE_NET_RES *teeNetRes);

    Config config_;
    void *teeCfg_ = nullptr;
    DG_ConfigOpts *cfgOpts_ = nullptr;
    std::unique_ptr<TeeCtxManager> teeCtxManager_;
};

} // namespace kcal

#endif // CONTEXT_H
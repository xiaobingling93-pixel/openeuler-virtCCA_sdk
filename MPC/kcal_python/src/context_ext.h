// Copyright (c) Huawei Technologies Co., Ltd. 2025-2025. All rights reserved.

#pragma once

#include <functional>
#include <memory>
#include <cstring>

#include "kcal/core/context.h"

namespace kcal {

class ContextExt {
public:
    using SendCallback = std::function<int(const TeeNodeInfo &, const uint8_t *, size_t)>;
    using RecvCallback = std::function<int(const TeeNodeInfo &, uint8_t *, size_t)>;

    static std::shared_ptr<ContextExt> Create(KCAL_Config config, SendCallback sendCb, RecvCallback recvCb);

    ContextExt() = default;
    ~ContextExt();

    std::shared_ptr<Context> GetKcalContext() const { return kcalCtx_; }

    static ContextExt *GetCurrentContext() { return currentContext_; }

private:
    ContextExt(SendCallback sendCb, RecvCallback recvCb);

    static ContextExt *currentContext_;

    SendCallback sendCallback_;
    RecvCallback recvCallback_;
    std::shared_ptr<Context> kcalCtx_;

    static int SendDataThunk(TeeNodeInfo *nodeInfo, unsigned char *buf, u64 len);
    static int RecvDataThunk(TeeNodeInfo *nodeInfo, unsigned char *buf, u64 *len);
};

} // namespace kcal
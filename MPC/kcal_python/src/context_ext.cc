// Copyright (c) Huawei Technologies Co., Ltd. 2025-2025. All rights reserved.

#include "context_ext.h"

namespace kcal {

ContextExt *ContextExt::currentContext_ = nullptr;

ContextExt::ContextExt(SendCallback sendCb, RecvCallback recvCb)
    : sendCallback_(std::move(sendCb)),
      recvCallback_(std::move(recvCb))
{
}

ContextExt::~ContextExt()
{
    if (currentContext_ == this) {
        currentContext_ = nullptr;
    }
}

std::shared_ptr<ContextExt> ContextExt::Create(KCAL_Config config, SendCallback sendCb, RecvCallback recvCb)
{
    auto ctx = std::shared_ptr<ContextExt>(new ContextExt(std::move(sendCb), std::move(recvCb)));

    currentContext_ = ctx.get();

    TEE_NET_RES net_res{};
    net_res.funcSendData = &ContextExt::SendDataThunk;
    net_res.funcRecvData = &ContextExt::RecvDataThunk;

    ctx->kcalCtx_ = Context::Create(config, &net_res);
    if (!ctx->kcalCtx_) {
        currentContext_ = nullptr;
        return nullptr;
    }

    return ctx;
}

int ContextExt::SendDataThunk(TeeNodeInfo *nodeInfo, unsigned char *buf, u64 len)
{
    if (!currentContext_ || !currentContext_->sendCallback_) {
        return -1;
    }

    try {
        return currentContext_->sendCallback_(*nodeInfo, buf, len);
    } catch (const std::exception &e) {
        return -1;
    }
}

int ContextExt::RecvDataThunk(TeeNodeInfo *nodeInfo, unsigned char *buf, u64 *len)
{
    if (!currentContext_ || !currentContext_->recvCallback_) {
        return -1;
    }

    try {
        return currentContext_->recvCallback_(*nodeInfo, buf, *len);
    } catch (const std::exception &e) {
        return -1;
    }
}

} // namespace kcal
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

#ifndef KCAL_MIDDLEWARE_KCAL_REVEAL_SHARE_H
#define KCAL_MIDDLEWARE_KCAL_REVEAL_SHARE_H

#include "kcal/core/context.h"
#include "kcal/utils/io.h"

namespace kcal {

class RevealShare {
public:
    explicit RevealShare(std::shared_ptr<Context> context) : context_(std::move(context)) {}

    static std::unique_ptr<RevealShare> Create(std::shared_ptr<Context> context);

    int Run(const io::MpcShare *share, io::Output &output);

private:
    int Initialize();

    std::shared_ptr<Context> context_;
    DG_TeeCtx *dgTeeCtx_ = nullptr;
    std::unique_ptr<DG_Arithmetic_Opts> opts_;
    bool initialized_ = false;
};

} // namespace kcal

#endif // KCAL_MIDDLEWARE_KCAL_REVEAL_SHARE_H

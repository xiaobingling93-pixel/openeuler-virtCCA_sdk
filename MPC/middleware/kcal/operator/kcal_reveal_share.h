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

#include "kcal/operator/kcal_arithmetic.h"

namespace kcal {

class RevealShare : public Arithmetic {
public:
    RevealShare() = default;
    ~RevealShare() override = default;

    int GetTeeCtx(const std::shared_ptr<Context> &context) override;
    KCAL_AlgorithmsType GetType() const override { return KCAL_AlgorithmsType::REVEAL_SHARE; }

    int Run(const io::KcalMpcShare *share, io::KcalOutput &output);
};

} // namespace kcal

#endif // KCAL_MIDDLEWARE_KCAL_REVEAL_SHARE_H

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

#ifndef KCAL_MIDDLEWARE_KCAL_MAXIMUM_H
#define KCAL_MIDDLEWARE_KCAL_MAXIMUM_H

#include "kcal/operator/kcal_arithmetic.h"

namespace kcal {

class Max : public Arithmetic {
public:
    Max() = default;
    ~Max() override = default;

    int GetTeeCtx(const std::shared_ptr<Context> &context) override;
    KCAL_AlgorithmsType GetType() const override { return KCAL_AlgorithmsType::MAX; }

    int Run(const io::KcalMpcShareSet &shareSet, io::KcalMpcShare *&outShare);
};

class Min : public Arithmetic {
public:
    Min() = default;
    ~Min() override = default;

    int GetTeeCtx(const std::shared_ptr<Context> &context) override;
    KCAL_AlgorithmsType GetType() const override { return KCAL_AlgorithmsType::MIN; }

    int Run(const io::KcalMpcShareSet &shareSet, io::KcalMpcShare *&outShare);
};

} // namespace kcal

#endif // KCAL_MIDDLEWARE_KCAL_MAXIMUM_H

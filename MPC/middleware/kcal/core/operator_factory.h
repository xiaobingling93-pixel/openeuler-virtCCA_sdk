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

#ifndef OPERATOR_FACTORY_H
#define OPERATOR_FACTORY_H

#include <memory>

#include "kcal/operator/kcal_make_share.h"
#include "kcal/operator/kcal_pir.h"
#include "kcal/operator/kcal_psi.h"
#include "kcal/operator/kcal_reveal_share.h"

namespace kcal {

class OperatorFactory {
public:
    static std::unique_ptr<Psi> CreatePsi(std::shared_ptr<Context> context);
    static std::unique_ptr<Pir> CreatePir(std::shared_ptr<Context> context);
    static std::unique_ptr<MakeShare> CreateMakeShare(std::shared_ptr<Context> context);
    static std::unique_ptr<RevealShare> CreateRevealShare(std::shared_ptr<Context> context);

    static std::shared_ptr<MpcOperatorBase> CreateMpc(std::shared_ptr<Context> context, KCAL_AlgorithmsType type);
};

} // namespace kcal

#endif // OPERATOR_FACTORY_H

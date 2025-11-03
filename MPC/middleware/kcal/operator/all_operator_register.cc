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

#include "kcal/operator/all_operator_register.h"
#include <mutex>
#include "kcal/core/operator_registry.h"
#include "kcal/operator/kcal_psi.h"
#include "kcal/operator/kcal_pir.h"
#include "kcal/operator/kcal_make_share.h"
#include "kcal/operator/kcal_reveal_share.h"
#include "kcal/operator/kcal_sum.h"
#include "kcal/operator/kcal_avg.h"
#include "kcal/operator/kcal_maximum.h"

namespace kcal {

namespace {

void RegisterAllOpsImpl()
{
    auto &registry = OperatorRegistry::Instance();
    registry.RegisterOperator<Psi>(KCAL_AlgorithmsType::PSI);
    registry.RegisterOperator<Pir>(KCAL_AlgorithmsType::PIR);
    registry.RegisterOperator<MakeShare>(KCAL_AlgorithmsType::MAKE_SHARE);
    registry.RegisterOperator<RevealShare>(KCAL_AlgorithmsType::REVEAL_SHARE);
    registry.RegisterOperator<Add>(KCAL_AlgorithmsType::ADD);
    registry.RegisterOperator<Sub>(KCAL_AlgorithmsType::SUB);
    registry.RegisterOperator<Mul>(KCAL_AlgorithmsType::MUL);
    registry.RegisterOperator<Div>(KCAL_AlgorithmsType::DIV);
    registry.RegisterOperator<Less>(KCAL_AlgorithmsType::LESS);
    registry.RegisterOperator<LessEqual>(KCAL_AlgorithmsType::LESS_EQUAL);
    registry.RegisterOperator<Greater>(KCAL_AlgorithmsType::GREATER);
    registry.RegisterOperator<GreaterEqual>(KCAL_AlgorithmsType::GREATER_EQUAL);
    registry.RegisterOperator<Equal>(KCAL_AlgorithmsType::EQUAL);
    registry.RegisterOperator<NoEqual>(KCAL_AlgorithmsType::NO_EQUAL);
    registry.RegisterOperator<Sum>(KCAL_AlgorithmsType::SUM);
    registry.RegisterOperator<Avg>(KCAL_AlgorithmsType::AVG);
    registry.RegisterOperator<Max>(KCAL_AlgorithmsType::MAX);
    registry.RegisterOperator<Min>(KCAL_AlgorithmsType::MIN);
}

} // namespace

void RegisterAllOps()
{
    static std::once_flag flag;
    std::call_once(flag, RegisterAllOpsImpl);
}

} // namespace kcal

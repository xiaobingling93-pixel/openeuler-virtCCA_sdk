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

#ifndef KCAL_PSI_H
#define KCAL_PSI_H

#include "kcal/api/kcal_api.h"
#include "kcal/core/context.h"
#include "kcal/core/mpc_operator_base.h"

namespace kcal {

class Psi {
public:
    explicit Psi(std::shared_ptr<Context> context);
    ~Psi();

    bool IsInitialized() const { return initialized_; }

    static std::unique_ptr<Psi> Create(std::shared_ptr<Context> context);

    int Run(const io::Input &input, io::Output &output, DG_TeeMode outputMode);

private:
    int Initialize();

    std::shared_ptr<Context> context_;

    DG_TeeCtx *dgTeeCtx_ = nullptr;
    std::unique_ptr<DG_PrivateSet_Opts> opts_;

    bool initialized_ = false;
};

} // namespace kcal

#endif // KCAL_PSI_H

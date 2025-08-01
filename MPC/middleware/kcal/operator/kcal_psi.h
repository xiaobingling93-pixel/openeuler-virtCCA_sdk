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

#include <memory>
#include "kcal/api/kcal_api.h"
#include "kcal/core/context.h"

namespace kcal {

class Psi {
public:
    Psi();
    ~Psi();

    Psi(const Psi &) = delete;
    Psi &operator=(const Psi &) = delete;

    int Init(std::shared_ptr<Context> ctx);
    int Run(DG_TeeInput *input, DG_TeeOutput **output, DG_TeeMode outputMode);

private:
    DG_TeeCtx *dgTeeCtx_ = nullptr;
    std::shared_ptr<Context> baseCtx_ = nullptr;
    std::unique_ptr<DG_PrivateSet_Opts> opts_;
};

}

#endif // KCAL_PSI_H

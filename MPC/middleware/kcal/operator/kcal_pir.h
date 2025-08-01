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

#ifndef KCAL_PIR_H
#define KCAL_PIR_H

#include <memory>
#include "kcal/core/context.h"

namespace kcal {

class Pir {
public:
    Pir();
    ~Pir();

    Pir(const Pir &) = delete;
    Pir &operator=(const Pir &) = delete;

    int Init(std::shared_ptr<Context> ctx);
    int ServerPreProcess(DG_PairList *pairList);
    int ClientQuery(DG_TeeInput *input, DG_TeeOutput **output, DG_DummyMode dummyMode);
    int ServerAnswer();

private:
    DG_TeeCtx *dgTeeCtx_ = nullptr;
    std::shared_ptr<Context> baseCtx_;
    std::unique_ptr<DG_PIR_Opts> opts_;
    DG_BucketMap *bucketMap_ = nullptr;
};

}

#endif // KCAL_PIR_H

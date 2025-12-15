# Copyright (c) Huawei Technologies Co., Ltd. 2025-2025. All rights reserved.

from __future__ import annotations

import socket
import sys

import kcal
import argparse

import socket_util

_client_socket = None
_server_socket = None

kcal.register_all_ops()

"""
server:
    nodeId: 0
    socket: _client_socket
client:
    nodeId: 1
    socket: _server_socket
"""


def get_fd(node_info: dict) -> socket.socket:
    return _server_socket if node_info['nodeId'] == 0 else _client_socket


def on_send_data(node_info: dict, data_buffer: memoryview) -> int:
    s = get_fd(node_info)
    return socket_util.send_data(s, data_buffer)


def on_recv_data(node_info: dict, buffer: memoryview) -> int:
    s = get_fd(node_info)
    return socket_util.recv_data(s, buffer)


def create_context(is_server: bool):
    """Create and return KCAL context for testing"""
    config = kcal.Config()
    config.nodeId = 0 if is_server else 1
    config.worldSize = 2
    config.fixBits = 3
    config.threadCount = 32
    config.useSMAlg = False

    return kcal.Context.create(config, on_send_data, on_recv_data)


def test_basic_arithmetic(context, is_server: bool):
    """Test basic arithmetic operations: ADD, SUB, MUL, DIV"""
    print("\n=== Testing Basic Arithmetic Operations ===")
    
    # Create operators
    make_share_op = kcal.create_operator(context, kcal.AlgorithmsType.MAKE_SHARE)
    reveal_share_op = kcal.create_operator(context, kcal.AlgorithmsType.REVEAL_SHARE)
    add_op = kcal.create_operator(context, kcal.AlgorithmsType.ADD)
    sub_op = kcal.create_operator(context, kcal.AlgorithmsType.SUB)
    mul_op = kcal.create_operator(context, kcal.AlgorithmsType.MUL)
    div_op = kcal.create_operator(context, kcal.AlgorithmsType.DIV)
    
    # Test data
    input1 = [10, 20, 30, 40]
    input2 = [5, 10, 15, 20]
    
    import time
    start_time = time.time()

    share1 = kcal.MpcShare.Create()
    share2 = kcal.MpcShare.Create()
    
    if is_server:
        print("Server: Processing arithmetic operations...")
        
        # Create shares for both inputs
        make_share_op.run(input1, 1, share1)  # isRecvShare = 1
        make_share_op.run(input2, 1, share2)

    else:
        print("Client: Processing arithmetic operations...")

        # Create shares for both inputs
        make_share_op.run(input1, 0, share1)  # isRecvShare = 0
        make_share_op.run(input2, 0, share2)
        
    # Test ADD: (10+5, 20+10, 30+15, 40+20) = [15, 30, 45, 60]
    add_out_share = kcal.MpcShare.Create()
    add_result = add_op.run([share1, share2], add_out_share)

    # Test SUB: (10-5, 20-10, 30-15, 40-20) = [5, 10, 15, 20]
    sub_out_share = kcal.MpcShare.Create()
    sub_result = sub_op.run([share1, share2], sub_out_share)

    # Test MUL: (10*5, 20*10, 30*15, 40*20) = [50, 200, 450, 800]
    mul_out_share = kcal.MpcShare.Create()
    mul_result = mul_op.run([share1, share2], mul_out_share )

    # Test DIV: (10/5, 20/10, 30/15, 40/20) = [2, 2, 2, 2]
    div_out_share = kcal.MpcShare.Create()
    div_result = div_op.run([share1, share2], div_out_share)

    # Reveal results
    add_output = []
    sub_output = []
    mul_output = []
    div_output = []

    reveal_share_op.run(add_out_share, add_output)
    reveal_share_op.run(sub_out_share, sub_output)
    reveal_share_op.run(mul_out_share, mul_output)
    reveal_share_op.run(div_out_share, div_output)

    print(f"ADD result: {add_output}")
    print(f"SUB result: {sub_output}")
    print(f"MUL result: {mul_output}")
    print(f"DIV result: {div_output}")

    end_time = time.time()
    duration_ms = (end_time - start_time) * 1000
    print(f"Basic arithmetic test completed in: {duration_ms:.2f} ms")


def test_comparison_operations(context, is_server: bool):
    """Test comparison operations: LESS, GREATER, EQUAL, etc."""
    print("\n=== Testing Comparison Operations ===")
    
    # Create operators
    make_share_op = kcal.create_operator(context, kcal.AlgorithmsType.MAKE_SHARE)
    reveal_share_op = kcal.create_operator(context, kcal.AlgorithmsType.REVEAL_SHARE)
    lt_op = kcal.create_operator(context, kcal.AlgorithmsType.LESS)
    gt_op = kcal.create_operator(context, kcal.AlgorithmsType.GREATER)
    eq_op = kcal.create_operator(context, kcal.AlgorithmsType.EQUAL)
    less_eq_op = kcal.create_operator(context, kcal.AlgorithmsType.LESS_EQUAL)
    greater_eq_op = kcal.create_operator(context, kcal.AlgorithmsType.GREATER_EQUAL)
    no_eq_op = kcal.create_operator(context, kcal.AlgorithmsType.NO_EQUAL)
    
    # Test data
    input1 = [10, 20, 30, 40]
    input2 = [15, 20, 25, 50]
    
    import time
    start_time = time.time()

    share1 = kcal.MpcShare.Create()
    share2 = kcal.MpcShare.Create()
    
    if is_server:
        print("Server: Processing comparison operations...")
        
        # Create shares
        make_share_op.run(input1, 1, share1)  # isRecvShare = 1
        make_share_op.run(input2, 1, share2)

    else:
        print("Client: Processing comparison operations...")

        make_share_op.run(input1, 0, share1)  # isRecvShare = 0
        make_share_op.run(input2, 0, share2)
        
    # Test comparison operations
    lt_out_share = kcal.MpcShare.Create()
    lt_op.run([share1, share2], lt_out_share)         # 10<15, 20<20, 30<25, 40<50 = [1,0,0,1]

    gt_out_share = kcal.MpcShare.Create()
    gt_op.run([share1, share2], gt_out_share)         # 10>15, 20>20, 30>25, 40>50 = [0,0,1,0]

    eq_out_share = kcal.MpcShare.Create()
    eq_op.run([share1, share2], eq_out_share)         # 10=15, 20=20, 30=25, 40=50 = [0,1,0,0]

    # Reveal results
    lt_output = []
    gt_output = []
    eq_output = []

    reveal_share_op.run(lt_out_share, lt_output)
    reveal_share_op.run(gt_out_share, gt_output)
    reveal_share_op.run(eq_out_share, eq_output)

    print(f"LESS (input1<input2) result: {lt_output}")
    print(f"GREATER (input1>input2) result: {gt_output}")
    print(f"EQUAL (input1==input2) result: {eq_output}")

    end_time = time.time()
    duration_ms = (end_time - start_time) * 1000
    print(f"Comparison operations test completed in: {duration_ms:.2f} ms")


def test_aggregate_operations(context, is_server: bool):
    """Test aggregate operations: SUM, AVG, MAX, MIN"""
    print("\n=== Testing Aggregate Operations ===")
    
    # Create operators
    make_share_op = kcal.create_operator(context, kcal.AlgorithmsType.MAKE_SHARE)
    reveal_share_op = kcal.create_operator(context, kcal.AlgorithmsType.REVEAL_SHARE)
    sum_op = kcal.create_operator(context, kcal.AlgorithmsType.SUM)
    avg_op = kcal.create_operator(context, kcal.AlgorithmsType.AVG)
    max_op = kcal.create_operator(context, kcal.AlgorithmsType.MAX)
    min_op = kcal.create_operator(context, kcal.AlgorithmsType.MIN)
    
    # Test data from multiple parties
    input = [10, 20, 30, 40]  # Party 1
    
    import time
    start_time = time.time()

    share = kcal.MpcShare.Create()
    
    if is_server:
        print("Server: Processing aggregate operations...")
        
        # Create shares
        make_share_op.run(input, 1, share)

    else:
        print("Client: Processing aggregate operations...")

        # Create shares
        make_share_op.run(input, 0, share)
        
    # Test aggregate operations (combine shares from both parties)
    sum_out_share = kcal.MpcShare.Create()
    avg_out_share = kcal.MpcShare.Create()
    max_out_share = kcal.MpcShare.Create()
    min_out_share = kcal.MpcShare.Create()

    sum_op.run([share], sum_out_share)
    avg_op.run([share], avg_out_share)
    max_op.run([share], max_out_share)
    min_op.run([share], min_out_share)

    # Reveal results
    sum_output = []
    avg_output = []
    max_output = []
    min_output = []

    reveal_share_op.run(sum_out_share, sum_output)
    reveal_share_op.run(avg_out_share, avg_output)
    reveal_share_op.run(max_out_share, max_output)
    reveal_share_op.run(min_out_share, min_output)

    print(f"SUM result: {sum_output}")
    print(f"AVG result: {avg_output}")
    print(f"MAX result: {max_output}")
    print(f"MIN result: {min_output}")

    end_time = time.time()
    duration_ms = (end_time - start_time) * 1000
    print(f"Aggregate operations test completed in: {duration_ms:.2f} ms")


def test_share_management(context, is_server: bool):
    """Test share management operations: MAKE_SHARE, REVEAL_SHARE"""
    print("\n=== Testing Share Management ===")
    
    make_share_op = kcal.create_operator(context, kcal.AlgorithmsType.MAKE_SHARE)
    reveal_share_op = kcal.create_operator(context, kcal.AlgorithmsType.REVEAL_SHARE)
    
    # Test data with different types
    test_inputs = [
        [1, 2, 3, 4, 5],           # Small integers
        [100, 200, 300, 400, 500], # Medium integers  
        [1000, 2000, 3000, 4000],    # Large integers
    ]
    
    for i, test_input in enumerate(test_inputs):
        print(f"\nTest case {i+1}: {test_input}")
        
        import time
        start_time = time.time()

        share = kcal.MpcShare.Create()
        
        if is_server:
            # Create share (server always receives shares)
            make_share_op.run(test_input, 1, share)
            
            # Reveal the share back to original values
            output = []
            reveal_share_op.run(share, output)
            
            print(f"Revealed values: {output}")
            
        else:
            # Create share (client doesn't receive shares)
            make_share_op.run(test_input, 0, share)
            
            # Reveal the share back to original values  
            output = []
            reveal_share_op.run(share, output)
            
            print(f"Revealed values: {output}")
        
        end_time = time.time()
        duration_ms = (end_time - start_time) * 1000
        print(f"Share management test completed in: {duration_ms:.2f} ms")


def run_comprehensive_tests(is_server: bool):
    """Run all tests for the new arithmetic operators"""
    print(f"=== KCAL Arithmetic Operators Test Suite ===")
    print(f"Running as: {'Server' if is_server else 'Client'}")
    
    context = create_context(is_server)
    
    try:
        # Run all test categories
        test_share_management(context, is_server)
        test_basic_arithmetic(context, is_server) 
        test_comparison_operations(context, is_server)
        test_aggregate_operations(context, is_server)
        
        print("\n=== All Tests Completed Successfully! ===")
        
    except Exception as e:
        print(f"Test failed with error: {e}")
        import traceback
        traceback.print_exc()



def create_parser():
    """Create and return the argument parser"""
    parser = argparse.ArgumentParser(description="KCAL python wrapper demo.")
    try:
        # Main mode selection
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument("--server", action="store_true", default=False, help="start server")
        group.add_argument("--client", action="store_true", default=False, help="start client")
        
        # Test selection
        test_group = parser.add_mutually_exclusive_group()
        test_group.add_argument("--test-all", action="store_true", default=True, 
                               help="run comprehensive tests for all arithmetic operators (default)")
        test_group.add_argument("--test-basic", action="store_true", default=False,
                               help="test basic arithmetic operations (ADD, SUB, MUL, DIV)")
        test_group.add_argument("--test-comparison", action="store_true", default=False,
                               help="test comparison operations (LESS, GREATER, EQUAL, etc.)")
        test_group.add_argument("--test-aggregate", action="store_true", default=False,
                               help="test aggregate operations (SUM, AVG, MAX, MIN)")
        test_group.add_argument("--test-shares", action="store_true", default=False,
                               help="test share management (MAKE_SHARE, REVEAL_SHARE)")
        test_group.add_argument("--original", action="store_true", default=False,
                               help="run original demo for compatibility")
        
        # Network configuration
        parser.add_argument("--host", type=str, default="127.0.0.1", 
                          help="server host address (default: 127.0.0.1)")
        parser.add_argument("-p", "--port", type=int, required=True,
                          help="port number for communication")
        
        return parser
    except argparse.ArgumentParser:
        parser.print_help()
        sys.exit(1)


def main(argv=None):
    parser = create_parser()
    args = parser.parse_args(argv)

    global _client_socket, _server_socket
    
    if args.server:
        _client_socket = socket_util.init_server(args.host, args.port)
        try:
            if args.test_basic:
                context = create_context(True)
                test_basic_arithmetic(context, True)
            elif args.test_comparison:
                context = create_context(True)
                test_comparison_operations(context, True)
            elif args.test_aggregate:
                context = create_context(True)
                test_aggregate_operations(context, True)
            elif args.test_shares:
                context = create_context(True)
                test_share_management(context, True)
            else:  # default: test_all
                run_comprehensive_tests(True)
        finally:
            _client_socket.close()
            
    elif args.client:
        _server_socket = socket_util.init_client(args.host, args.port)
        try:
            if args.test_basic:
                context = create_context(False)
                test_basic_arithmetic(context, False)
            elif args.test_comparison:
                context = create_context(False)
                test_comparison_operations(context, False)
            elif args.test_aggregate:
                context = create_context(False)
                test_aggregate_operations(context, False)
            elif args.test_shares:
                context = create_context(False)
                test_share_management(context, False)
            else:  # default: test_all
                run_comprehensive_tests(False)
        finally:
            _server_socket.close()


if __name__ == "__main__":
    main()

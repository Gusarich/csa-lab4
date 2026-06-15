.equ STACK_INIT, 0x01000000
.equ RX_CAP, 128
.equ LINE_CAP, 32
.equ MAX_N, 92681
.equ FLAG_EOF, 1
.equ FLAG_DEVICE_OVERRUN, 2
.equ FLAG_RING_OVERFLOW, 4

.section .vectors
.org 0x000000
.word _start
.word irq_input
.space 56

.section .text
.org 0x000040
.macro push reg
    addi sp, sp, -4
    sw reg, 0(sp)
.endm

.macro pop reg
    lw reg, 0(sp)
    addi sp, sp, 4
.endm

_start:
    li sp, STACK_INIT
    ei

    la a0, line_buf
    li a1, LINE_CAP
    call read_line_pstr
    la t0, input_error
    lw t1, 0(t0)
    bne t1, zero, print_input_error

    call parse_n_line
    la t0, input_error
    lw t1, 0(t0)
    bne t1, zero, print_input_error
    la t0, range_error
    lw t1, 0(t0)
    bne t1, zero, print_range_error

    call compute_prob2
    call print_u64
    call put_newline
    j done

print_input_error:
    la a0, err_input
    call puts_pstr
    j done

print_range_error:
    la a0, err_range
    call puts_pstr

done:
    halt

parse_n_line:
    la a3, line_buf
    lw t0, 0(a3)
    beq t0, zero, parse_input_error
    li t1, 0
    li t3, 0
parse_n_loop:
    beq t1, t0, parse_n_finish
    addi a0, t1, 1
    li a1, 2
    sll a0, a0, a1
    add a0, a3, a0
    lw t5, 0(a0)

    li a0, '0'
    bltu t5, a0, parse_input_error
    li a0, ':'
    bgeu t5, a0, parse_input_error

    li a0, '0'
    sub a1, t5, a0
    li a0, 429496729
    bltu a0, t3, parse_input_error
    bne t3, a0, parse_n_accumulate
    li a0, 5
    bltu a0, a1, parse_input_error
parse_n_accumulate:
    li a0, 10
    mul t3, t3, a0
    add t3, t3, a1
    addi t1, t1, 1
    j parse_n_loop

parse_n_finish:
    li a0, MAX_N
    bltu a0, t3, parse_range_error
    la a0, n_value
    sw t3, 0(a0)
    ret

parse_input_error:
    la t0, input_error
    li t1, 1
    sw t1, 0(t0)
    ret

parse_range_error:
    la t0, range_error
    li t1, 1
    sw t1, 0(t0)
    ret

compute_prob2:
    la t2, n_value
    lw t1, 0(t2)
    li t0, 1
    li a0, 0
    li a1, 0
    li a2, 0
prob2_loop:
    bltu t1, t0, prob2_after_loop
    add a0, a0, t0
    mul t3, t0, t0
    mulhu t4, t0, t0
    add a2, a2, t3
    sltu t5, a2, t3
    add a1, a1, t4
    add a1, a1, t5
    addi t0, t0, 1
    j prob2_loop

prob2_after_loop:
    mul t3, a0, a0
    mulhu t4, a0, a0
    sltu t5, t3, a2
    sub rv, t3, a2
    sub a0, t4, a1
    sub a0, a0, t5
    move a1, rv
    ret

puts_pstr:
    lw t0, 0(a0)
    addi t1, a0, 4
puts_pstr_loop:
    beq t0, zero, puts_pstr_done
    lw t2, 0(t1)
    out OUT_DATA, t2
    addi t1, t1, 4
    addi t0, t0, -1
    j puts_pstr_loop
puts_pstr_done:
    ret

put_newline:
    li a0, '\n'
    out OUT_DATA, a0
    ret

print_u64:
    la t0, decimal_powers
    li t1, 20
    li t2, 0
print_u64_power:
    lw t4, 0(t0)
    lw t5, 4(t0)
    li t3, 0
print_u64_sub_loop:
    bltu a0, t4, print_u64_emit
    bltu t4, a0, print_u64_can_sub
    bltu a1, t5, print_u64_emit
print_u64_can_sub:
    sltu rv, a1, t5
    sub a1, a1, t5
    sub a0, a0, t4
    sub a0, a0, rv
    addi t3, t3, 1
    j print_u64_sub_loop
print_u64_emit:
    bne t2, zero, print_u64_output
    bne t3, zero, print_u64_output
    li rv, 1
    beq t1, rv, print_u64_output
    j print_u64_next
print_u64_output:
    li t2, 1
    addi t3, t3, '0'
    out OUT_DATA, t3
print_u64_next:
    addi t0, t0, 8
    addi t1, t1, -1
    bne t1, zero, print_u64_power
    ret

read_line_pstr:
    push ra
    move a3, a0
    li a2, 0
read_line_loop:
    call rx_pop
    bne a0, zero, read_line_have_char
    la t0, rx_flags
    lw t1, 0(t0)
    andi t1, t1, FLAG_EOF
    bne t1, zero, read_line_done
    j read_line_loop
read_line_have_char:
    li t0, '\n'
    beq rv, t0, read_line_done
    bgeu a2, a1, read_line_overflow
    addi t0, a2, 1
    li t1, 2
    sll t0, t0, t1
    add t0, a3, t0
    sw rv, 0(t0)
    addi a2, a2, 1
    j read_line_loop

read_line_overflow:
    la t0, input_error
    li t1, 1
    sw t1, 0(t0)
read_line_drain:
    call rx_pop
    bne a0, zero, read_line_drain_char
    la t0, rx_flags
    lw t1, 0(t0)
    andi t1, t1, FLAG_EOF
    bne t1, zero, read_line_done
    j read_line_drain
read_line_drain_char:
    li t0, '\n'
    beq rv, t0, read_line_done
    j read_line_drain

read_line_done:
    sw a2, 0(a3)
    pop ra
    ret

rx_pop:
    di
    la t0, rx_count
    lw t1, 0(t0)
    beq t1, zero, rx_pop_empty

    la t2, rx_head
    lw t3, 0(t2)
    li t4, 2
    sll t4, t3, t4
    la t5, rx_buf
    add t5, t5, t4
    lw rv, 0(t5)

    addi t3, t3, 1
    li t4, RX_CAP
    bltu t3, t4, rx_pop_head_ok
    li t3, 0
rx_pop_head_ok:
    sw t3, 0(t2)
    addi t1, t1, -1
    sw t1, 0(t0)
    li a0, 1
    ei
    ret

rx_pop_empty:
    li a0, 0
    ei
    ret

irq_input:
    push t0
    push t1
    push t2
    push t3
    push t4
    push t5

    in k0, IN_STATUS
    andi k1, k0, 4
    beq k1, zero, irq_ready
    la t0, rx_flags
    lw t1, 0(t0)
    ori t1, t1, FLAG_DEVICE_OVERRUN
    sw t1, 0(t0)
    li k0, 2
    out IN_CTRL, k0

irq_ready:
    in k0, IN_STATUS
    andi k1, k0, 1
    beq k1, zero, irq_eof
    in k0, IN_DATA

    la t0, rx_count
    lw t1, 0(t0)
    li t2, RX_CAP
    bgeu t1, t2, irq_ring_full

    la t3, rx_tail
    lw t4, 0(t3)
    li t5, 2
    sll t5, t4, t5
    la t2, rx_buf
    add t2, t2, t5
    sw k0, 0(t2)

    addi t4, t4, 1
    li t5, RX_CAP
    bltu t4, t5, irq_tail_ok
    li t4, 0
irq_tail_ok:
    sw t4, 0(t3)
    addi t1, t1, 1
    sw t1, 0(t0)
    j irq_eof

irq_ring_full:
    la t0, rx_flags
    lw t1, 0(t0)
    ori t1, t1, FLAG_RING_OVERFLOW
    sw t1, 0(t0)

irq_eof:
    in k0, IN_STATUS
    andi k1, k0, 2
    beq k1, zero, irq_done
    la t0, rx_flags
    lw t1, 0(t0)
    ori t1, t1, FLAG_EOF
    sw t1, 0(t0)
    li k0, 1
    out IN_CTRL, k0

irq_done:
    pop t5
    pop t4
    pop t3
    pop t2
    pop t1
    pop t0
    iret

.section .rodata
err_input:
    .pstr "ERR_INPUT\n"
err_range:
    .pstr "ERR_RANGE\n"
decimal_powers:
    .word 0x8AC72304, 0x89E80000
    .word 0x0DE0B6B3, 0xA7640000
    .word 0x01634578, 0x5D8A0000
    .word 0x002386F2, 0x6FC10000
    .word 0x00038D7E, 0xA4C68000
    .word 0x00005AF3, 0x107A4000
    .word 0x00000918, 0x4E72A000
    .word 0x000000E8, 0xD4A51000
    .word 0x00000017, 0x4876E800
    .word 0x00000002, 0x540BE400
    .word 0x00000000, 0x3B9ACA00
    .word 0x00000000, 0x05F5E100
    .word 0x00000000, 0x00989680
    .word 0x00000000, 0x000F4240
    .word 0x00000000, 0x000186A0
    .word 0x00000000, 0x00002710
    .word 0x00000000, 0x000003E8
    .word 0x00000000, 0x00000064
    .word 0x00000000, 0x0000000A
    .word 0x00000000, 0x00000001

.section .data
rx_head:
    .word 0
rx_tail:
    .word 0
rx_count:
    .word 0
rx_flags:
    .word 0
input_error:
    .word 0
range_error:
    .word 0
n_value:
    .word 0
line_buf:
    .space 132

.section .bss
rx_buf:
    .space 512

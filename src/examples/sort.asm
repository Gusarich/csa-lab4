.equ STACK_INIT, 0x01000000
.equ RX_CAP, 128
.equ LINE_CAP, 256
.equ SORT_CAP, 32
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
    bne t1, zero, print_error

    call parse_sort_line
    la t0, input_error
    lw t1, 0(t0)
    bne t1, zero, print_error

    call sort_u32
    call print_array
    j done

print_error:
    la a0, err_input
    call puts_pstr

done:
    halt

parse_sort_line:
    push ra
    la a3, line_buf
    lw t0, 0(a3)
    li t1, 0
    li t2, 0
    li t3, 0
    li t4, 0
parse_loop:
    beq t1, t0, parse_finish
    addi a0, t1, 1
    li a1, 2
    sll a0, a0, a1
    add a0, a3, a0
    lw t5, 0(a0)

    li a0, '0'
    bltu t5, a0, parse_delimiter
    li a0, ':'
    bgeu t5, a0, parse_bad_char

    li a0, '0'
    sub a1, t5, a0
    li a0, 429496729
    bltu a0, t3, parse_bad_char
    bne t3, a0, parse_accumulate
    li a0, 5
    bltu a0, a1, parse_bad_char
parse_accumulate:
    li a0, 10
    mul t3, t3, a0
    add t3, t3, a1
    li t4, 1
    addi t1, t1, 1
    j parse_loop

parse_delimiter:
    li a0, ' '
    bne t5, a0, parse_bad_char
    beq t4, zero, parse_skip_space
    call process_sort_token
parse_skip_space:
    addi t1, t1, 1
    j parse_loop

parse_finish:
    beq t4, zero, parse_validate
    call process_sort_token
parse_validate:
    beq t2, zero, parse_bad_char
    addi t2, t2, -1
    la a0, expected_count
    lw a1, 0(a0)
    bne t2, a1, parse_bad_char
    la a0, sort_count
    sw t2, 0(a0)
    pop ra
    ret

parse_bad_char:
    la t0, input_error
    li t1, 1
    sw t1, 0(t0)
    pop ra
    ret

process_sort_token:
    beq t2, zero, process_count
    li a0, 2
    addi a1, t2, -1
    sll a1, a1, a0
    la a0, numbers
    add a0, a0, a1
    sw t3, 0(a0)
    addi t2, t2, 1
    li t3, 0
    li t4, 0
    ret

process_count:
    li a0, SORT_CAP
    bltu a0, t3, parse_bad_char
    la a0, expected_count
    sw t3, 0(a0)
    addi t2, t2, 1
    li t3, 0
    li t4, 0
    ret

sort_u32:
    la t5, sort_count
    lw t5, 0(t5)
    li t0, 0
sort_outer:
    bgeu t0, t5, sort_done
    li t1, 0
    sub t2, t5, t0
    addi t2, t2, -1
sort_inner:
    bgeu t1, t2, sort_outer_next
    li a0, 2
    sll a1, t1, a0
    la a2, numbers
    add a2, a2, a1
    lw t3, 0(a2)
    lw t4, 4(a2)
    bltu t4, t3, sort_swap
    j sort_inner_next
sort_swap:
    sw t4, 0(a2)
    sw t3, 4(a2)
sort_inner_next:
    addi t1, t1, 1
    j sort_inner
sort_outer_next:
    addi t0, t0, 1
    j sort_outer
sort_done:
    ret

print_array:
    push ra
    li t0, 0
    la t1, print_index
    sw t0, 0(t1)
print_array_loop:
    la t1, print_index
    lw t0, 0(t1)
    la t2, sort_count
    lw t3, 0(t2)
    bgeu t0, t3, print_array_done
    beq t0, zero, print_array_value
    li a0, ' '
    out OUT_DATA, a0
print_array_value:
    li a0, 2
    sll a1, t0, a0
    la a2, numbers
    add a2, a2, a1
    lw a0, 0(a2)
    call print_u32
    la t1, print_index
    lw t0, 0(t1)
    addi t0, t0, 1
    sw t0, 0(t1)
    j print_array_loop
print_array_done:
    li a0, '\n'
    out OUT_DATA, a0
    pop ra
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

print_u32:
    move a1, a0
    li a0, 0
    j print_u64

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
expected_count:
    .word 0
sort_count:
    .word 0
print_index:
    .word 0
numbers:
    .space 128
line_buf:
    .space 1028

.section .bss
rx_buf:
    .space 512

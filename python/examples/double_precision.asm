.equ STACK_INIT, 0x01000000

.section .vectors
.org 0x000000
.word _start
.word 0
.space 56

.section .text
.org 0x000040
_start:
    li sp, STACK_INIT

    la a0, add_label
    call puts_pstr
    li t0, 0xFFFFFFFF
    li t1, 1
    add a1, t0, t1
    sltu a0, a1, t0
    call print_u64
    call put_newline

    la a0, mul_label
    call puts_pstr
    li t0, 0xFFFFFFFF
    mul a1, t0, t0
    mulhu a0, t0, t0
    call print_u64
    call put_newline

done:
    halt

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

.section .rodata
add_label:
    .pstr "0xffffffff + 1 = "
mul_label:
    .pstr "0xffffffff * 0xffffffff = "
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

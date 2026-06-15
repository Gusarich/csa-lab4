.equ STACK_INIT, 0x01000000
.equ RX_CAP, 128
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

cat_loop:
    call rx_pop
    bne a0, zero, cat_emit
    la t0, rx_flags
    lw t1, 0(t0)
    andi t1, t1, FLAG_EOF
    bne t1, zero, done
    j cat_loop

cat_emit:
    out OUT_DATA, rv
    j cat_loop

done:
    halt

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

.section .data
rx_head:
    .word 0
rx_tail:
    .word 0
rx_count:
    .word 0
rx_flags:
    .word 0

.section .bss
rx_buf:
    .space 512

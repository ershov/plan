# Project {#project}

## Metadata {#metadata}

    next_id: 146

## Tickets {#tickets}

* ## Ticket: Epic: Language frontend {#1}

      status: open
      created: 2026-03-23 05:41:12 UTC
      updated: 2026-03-23 05:41:12 UTC

  Lexing, parsing, and semantic analysis for C and C++ source code.

  * ## Ticket: Task: Preprocessor {#2}

        status: open
        created: 2026-03-23 05:41:12 UTC
        updated: 2026-03-23 05:41:12 UTC

    Implement #include, #define, #ifdef, #pragma, and macro expansion. Handle trigraphs, line splicing, and stringification. Search paths for system and user headers.

    * ## Ticket: Subtask: Macro definition and expansion {#70}

          status: open
          created: 2026-03-23 05:54:35 UTC
          updated: 2026-03-23 05:54:35 UTC

      Implement `#define` for object-like and function-like macros. Handle variadic macros (`__VA_ARGS__`), stringification (`#`), and token pasting (`##`). Build a macro table that supports `#undef` and redefinition checks.

    * ## Ticket: Subtask: Include file resolution {#71}

          status: open
          created: 2026-03-23 05:54:35 UTC
          updated: 2026-03-23 05:54:35 UTC

      Implement `#include <...>` and `#include "..."` with configurable system and user search paths. Support `-I`, `-isystem`, and `-iquote` flags. Track include depth to detect circular includes and enforce a maximum nesting limit.

    * ## Ticket: Subtask: Conditional compilation {#72}

          status: open
          created: 2026-03-23 05:54:35 UTC
          updated: 2026-03-23 05:54:35 UTC

      Implement `#if`, `#ifdef`, `#ifndef`, `#elif`, `#else`, and `#endif`. Evaluate constant integer expressions in `#if` using a mini expression evaluator that handles `defined()`, integer arithmetic, and comparison operators.

    * ## Ticket: Subtask: Line splicing and trigraphs {#73}

          status: open
          created: 2026-03-23 05:54:35 UTC
          updated: 2026-03-23 05:54:35 UTC

      Handle backslash-newline line continuation before tokenization. Implement trigraph replacement (e.g., `??=` to `#`) with a warning. Process the input in a single pre-scan pass that produces a clean character stream for the lexer.

    * ## Ticket: Subtask: Pragma handling {#74}

          status: open
          created: 2026-03-23 05:54:35 UTC
          updated: 2026-03-23 05:54:35 UTC

      Implement `#pragma once`, `#pragma pack`, and `_Pragma()` operator. Provide a hook mechanism so the compiler driver can register custom pragma handlers. Unrecognized pragmas should emit a warning rather than an error.

  * ## Ticket: Task: C lexer {#3}

        status: open
        created: 2026-03-23 05:41:12 UTC
        updated: 2026-03-23 05:41:12 UTC

    Tokenize C source into keywords, identifiers, literals, operators, and punctuation. Handle integer, float, char, and string literals with all suffixes. Line and column tracking for diagnostics.

  * ## Ticket: Task: C++ lexer extensions {#4}

        status: open
        created: 2026-03-23 05:41:12 UTC
        updated: 2026-03-23 05:41:12 UTC

    Extend the C lexer for C++ keywords, user-defined literals, raw string literals, and template angle bracket disambiguation.

  * ## Ticket: Task: C parser {#5}

        status: open
        created: 2026-03-23 05:41:12 UTC
        updated: 2026-03-23 05:41:12 UTC

    Recursive descent parser for C11. Declarations, statements, expressions, struct/union/enum, typedef, function definitions. Produce an AST.

    * ## Ticket: Subtask: Declaration parsing {#75}

          status: open
          created: 2026-03-23 05:54:46 UTC
          updated: 2026-03-23 05:54:46 UTC

      Parse variable declarations, function declarations, and function definitions including storage-class specifiers, type qualifiers, and complex declarator syntax (pointers, arrays, function pointers). Handle `typedef` by feeding type names back into the lexer's identifier/type distinction.

    * ## Ticket: Subtask: Expression parsing {#76}

          status: open
          created: 2026-03-23 05:54:46 UTC
          updated: 2026-03-23 05:54:46 UTC

      Implement precedence-climbing or Pratt parsing for the full C operator set. Handle comma expressions, ternary operator, assignment, casts, sizeof, alignof, compound literals, and designated initializers. Produce expression AST nodes with source ranges.

    * ## Ticket: Subtask: Statement and control flow parsing {#77}

          status: open
          created: 2026-03-23 05:54:46 UTC
          updated: 2026-03-23 05:54:46 UTC

      Parse compound statements, if/else, for, while, do-while, switch/case/default, goto/labels, break, continue, and return. Track label declarations for goto validation. Handle C99 for-loop declarations.

    * ## Ticket: Subtask: Struct, union, and enum parsing {#78}

          status: open
          created: 2026-03-23 05:54:46 UTC
          updated: 2026-03-23 05:54:46 UTC

      Parse struct/union definitions with bit-fields, anonymous structs, and flexible array members. Parse enum definitions with optional explicit values. Handle forward declarations and incomplete type references.

    * ## Ticket: Subtask: AST node design {#79}

          status: open
          created: 2026-03-23 05:54:46 UTC
          updated: 2026-03-23 05:54:46 UTC

      Define the AST data structures covering all C11 constructs. Each node stores its source range, type annotation slot, and parent pointer. Use a bump allocator for AST memory to avoid per-node allocation overhead and ensure cache-friendly traversal.

  * ## Ticket: Task: C++ parser extensions {#6}

        status: open
        created: 2026-03-23 05:41:12 UTC
        updated: 2026-03-23 05:41:12 UTC

    Classes, templates, namespaces, operator overloading, lambda expressions, constexpr, concepts. Handle the most vexing parse and dependent name disambiguation.

    * ## Ticket: Subtask: Class and access control parsing {#80}

          status: open
          created: 2026-03-23 05:54:53 UTC
          updated: 2026-03-23 05:54:53 UTC

      Parse class/struct definitions with base classes, access specifiers, virtual functions, and friend declarations. Handle special member functions (constructors, destructors, copy/move operations) and in-class member initializers.

    * ## Ticket: Subtask: Template parsing {#81}

          status: open
          created: 2026-03-23 05:54:53 UTC
          updated: 2026-03-23 05:54:53 UTC

      Parse function templates, class templates, and variable templates with type, non-type, and template-template parameters. Handle explicit specialization and partial specialization syntax. Defer instantiation of template bodies until template arguments are known.

    * ## Ticket: Subtask: Namespace and using declarations {#82}

          status: open
          created: 2026-03-23 05:54:53 UTC
          updated: 2026-03-23 05:54:53 UTC

      Parse namespace definitions, unnamed namespaces, inline namespaces, namespace aliases, using-declarations, and using-directives. Implement qualified name lookup with the `::` operator across nested namespaces.

    * ## Ticket: Subtask: Lambda expression parsing {#83}

          status: open
          created: 2026-03-23 05:54:53 UTC
          updated: 2026-03-23 05:54:53 UTC

      Parse lambda expressions with capture lists (by-value, by-reference, init-captures), optional parameter lists, mutable specifier, trailing return types, and constexpr/consteval qualifiers. Lower lambda AST nodes into anonymous closure class representations.

    * ## Ticket: Subtask: Concept and requires-clause parsing {#84}

          status: open
          created: 2026-03-23 05:54:53 UTC
          updated: 2026-03-23 05:54:53 UTC

      Parse concept definitions and requires-clauses on templates and functions. Handle simple requirements, type requirements, compound requirements, and nested requirements in requires-expressions. Integrate constraints into overload resolution priority.

  * ## Ticket: Task: Semantic analysis {#7}

        status: open
        created: 2026-03-23 05:41:12 UTC
        updated: 2026-03-23 05:41:12 UTC

    Type checking, implicit conversions, overload resolution (C++), scope resolution, constant folding. Build symbol tables. Emit diagnostics with source ranges.

    * ## Ticket: Subtask: Symbol table and scope management {#85}

          status: open
          created: 2026-03-23 05:55:02 UTC
          updated: 2026-03-23 05:55:02 UTC

      Build a hierarchical symbol table supporting block scope, function scope, file scope, and (for C++) namespace/class scope. Support lookup that walks the scope chain, handles name hiding, and detects duplicate definitions.

    * ## Ticket: Subtask: Type checking and implicit conversions {#86}

          status: open
          created: 2026-03-23 05:55:02 UTC
          updated: 2026-03-23 05:55:02 UTC

      Implement the C/C++ type system including arithmetic types, pointer types, array-to-pointer decay, function types, and qualified types. Apply the implicit conversion sequences (integer promotions, usual arithmetic conversions, lvalue-to-rvalue) and emit diagnostics for invalid conversions.

    * ## Ticket: Subtask: Overload resolution (C++) {#87}

          status: open
          created: 2026-03-23 05:55:02 UTC
          updated: 2026-03-23 05:55:02 UTC

      Implement candidate gathering from the current scope, ADL (argument-dependent lookup), and conversion ranking. Compare candidates using the partial ordering rules for templates and the better-conversion-sequence tiebreakers. Emit clear ambiguity diagnostics when resolution fails.

    * ## Ticket: Subtask: Constant expression evaluation {#88}

          status: open
          created: 2026-03-23 05:55:02 UTC
          updated: 2026-03-23 05:55:02 UTC

      Evaluate `constexpr` and constant integer expressions at compile time. Support arithmetic, comparisons, ternary, casts, sizeof, and `constexpr` function calls (C++). Used by array bounds, case labels, template arguments, and `static_assert`.

    * ## Ticket: Subtask: Declaration validation and completeness checks {#89}

          status: open
          created: 2026-03-23 05:55:02 UTC
          updated: 2026-03-23 05:55:02 UTC

      Verify that types are complete where required, function signatures match between declaration and definition, `static_assert` conditions hold, and `_Alignas`/`alignof` constraints are respected. Check for unused variables, unreachable code after `return`, and missing return statements in non-void functions.

  * ## Ticket: Task: C standard library headers {#8}

        status: open
        created: 2026-03-23 05:41:12 UTC
        updated: 2026-03-23 05:41:12 UTC

    Ship minimal freestanding headers (stddef.h, stdint.h, stdarg.h, limits.h, float.h). Provide hosted headers that wrap platform libc.

  * ## Ticket: Task: C++ standard library headers {#9}

        status: open
        created: 2026-03-23 05:41:12 UTC
        updated: 2026-03-23 05:41:12 UTC

    Provide core headers: type_traits, utility, memory, string, vector, array, span, optional, variant, functional, algorithm, iostream, format.

* ## Ticket: Epic: Intermediate representation {#10}

      status: open
      created: 2026-03-23 05:41:12 UTC
      updated: 2026-03-23 05:41:12 UTC

  Platform-independent IR for optimization and code generation.

  * ## Ticket: Task: IR design and data structures {#11}

        status: open
        created: 2026-03-23 05:41:12 UTC
        updated: 2026-03-23 05:41:12 UTC

    Define SSA-based IR with basic blocks, phi nodes, and typed instructions. Support integer, float, pointer, aggregate, and vector types.

    * ## Ticket: Subtask: Type system and instruction set design {#90}

          status: open
          created: 2026-03-23 05:55:09 UTC
          updated: 2026-03-23 05:55:09 UTC

      Define the IR type hierarchy: integer types (i1, i8, i16, i32, i64), floating-point types (f32, f64), pointer type, vector types, array types, and struct types. Design the instruction set covering arithmetic, comparison, memory (load/store/alloca), control flow (br, switch, ret), phi nodes, and call instructions.

    * ## Ticket: Subtask: Basic block and CFG representation {#91}

          status: open
          created: 2026-03-23 05:55:09 UTC
          updated: 2026-03-23 05:55:09 UTC

      Implement basic blocks as ordered lists of instructions terminated by a single control-flow instruction. Each function holds a list of basic blocks with predecessor/successor edges forming the CFG. Provide iterators and graph trait implementations so standard algorithms (DFS, dominator tree, loop detection) work generically.

    * ## Ticket: Subtask: SSA construction and use-def chains {#92}

          status: open
          created: 2026-03-23 05:55:09 UTC
          updated: 2026-03-23 05:55:09 UTC

      Implement SSA form with def-use and use-def chains so that each value has a single definition point and every use links back to it. Provide efficient insertion and removal of uses when instructions are modified or deleted. Use an intrusive linked list of uses per value to avoid external hash maps.

  * ## Ticket: Task: AST to IR lowering {#12}

        status: open
        created: 2026-03-23 05:41:12 UTC
        updated: 2026-03-23 05:41:12 UTC

    Translate the AST into IR. Handle control flow (if, for, while, switch, goto), short-circuit evaluation, struct layout, and ABI-compliant function calls.

    * ## Ticket: Subtask: Expression and operator lowering {#93}

          status: open
          created: 2026-03-23 05:55:22 UTC
          updated: 2026-03-23 05:55:22 UTC

      Translate C/C++ expressions into IR instructions: arithmetic, bitwise, logical, comparison, pointer arithmetic, member access, array subscript. Handle short-circuit evaluation for `&&` and `||` by emitting conditional branches to merge blocks rather than computing boolean intermediates.

    * ## Ticket: Subtask: Control flow lowering {#94}

          status: open
          created: 2026-03-23 05:55:22 UTC
          updated: 2026-03-23 05:55:22 UTC

      Lower if/else, for, while, do-while, switch, goto, break, continue, and return into IR basic blocks and branches. For switch statements, decide between a jump table (dense case values) or binary search tree (sparse values) based on case density analysis.

    * ## Ticket: Subtask: Function call and ABI lowering {#95}

          status: open
          created: 2026-03-23 05:55:22 UTC
          updated: 2026-03-23 05:55:22 UTC

      Translate function calls into IR call instructions, applying the target ABI rules for argument passing and return values. Handle struct-by-value passing (splitting into registers or passing via hidden pointer), varargs setup, and callee-saved register annotations.

    * ## Ticket: Subtask: Aggregate type layout and access {#96}

          status: open
          created: 2026-03-23 05:55:22 UTC
          updated: 2026-03-23 05:55:22 UTC

      Compute struct/union memory layout respecting alignment and padding rules. Lower member access to GEP (get-element-pointer) instructions with field offsets. Handle bit-field packing by generating shift-and-mask sequences for reads and read-modify-write sequences for stores.

    * ## Ticket: Subtask: Initializer and global variable lowering {#97}

          status: open
          created: 2026-03-23 05:55:22 UTC
          updated: 2026-03-23 05:55:22 UTC

      Lower global variable definitions with constant initializers into IR global objects. Handle compound initializers (arrays, structs), designated initializers, zero-initialization, and string literal deduplication. Emit constructor functions for globals requiring runtime initialization (C++).

  * ## Ticket: Task: IR validation and pretty printer {#13}

        status: open
        created: 2026-03-23 05:41:12 UTC
        updated: 2026-03-23 05:41:12 UTC

    Verify SSA dominance, type consistency, and CFG integrity. Text-based IR dump for debugging and testing.

  * ## Ticket: Task: IR serialization {#14}

        status: open
        created: 2026-03-23 05:41:12 UTC
        updated: 2026-03-23 05:41:12 UTC

    Binary format for writing and reading IR modules. Used for LTO and caching precompiled headers.

* ## Ticket: Epic: Optimization passes {#15}

      status: open
      created: 2026-03-23 05:41:12 UTC
      updated: 2026-03-23 05:41:12 UTC

  Machine-independent optimizations on the IR.

  * ## Ticket: Task: Pass manager infrastructure {#16}

        status: open
        created: 2026-03-23 05:41:12 UTC
        updated: 2026-03-23 05:41:12 UTC

    Module and function pass pipeline. Dependency tracking between passes. Analysis preservation. Pass ordering and iteration.

    * ## Ticket: Subtask: Pass registration and pipeline construction {#98}

          status: open
          created: 2026-03-23 05:55:26 UTC
          updated: 2026-03-23 05:55:26 UTC

      Implement a pass registry where each optimization pass declares its name, required analyses, and preserved analyses. Build the pipeline from command-line flags (-O0, -O1, -O2, -O3, -Os) by populating a pass schedule. Support inserting, removing, and reordering passes for debugging.

    * ## Ticket: Subtask: Analysis management and caching {#99}

          status: open
          created: 2026-03-23 05:55:26 UTC
          updated: 2026-03-23 05:55:26 UTC

      Implement an analysis manager that lazily computes analyses (dominator tree, loop info, alias analysis) on demand and caches results. Track which analyses are invalidated by each transformation pass. Re-run invalidated analyses only when a subsequent pass requests them.

  * ## Ticket: Task: Scalar optimizations {#17}

        status: open
        created: 2026-03-23 05:41:12 UTC
        updated: 2026-03-23 05:41:12 UTC

    Constant propagation, dead code elimination, common subexpression elimination, strength reduction, loop-invariant code motion.

    * ## Ticket: Subtask: Constant propagation and folding {#100}

          status: open
          created: 2026-03-23 05:55:35 UTC
          updated: 2026-03-23 05:55:35 UTC

      Replace uses of variables known to hold constant values with the constant itself. Fold constant arithmetic at compile time. Use sparse conditional constant propagation (SCCP) to handle constants flowing through phi nodes and across branches.

    * ## Ticket: Subtask: Dead code elimination {#101}

          status: open
          created: 2026-03-23 05:55:35 UTC
          updated: 2026-03-23 05:55:35 UTC

      Remove instructions whose results are never used. Use a worklist-based approach starting from side-effect-free instructions with zero uses, then propagate: when an instruction is deleted, check if its operands become dead too.

    * ## Ticket: Subtask: Common subexpression elimination {#102}

          status: open
          created: 2026-03-23 05:55:35 UTC
          updated: 2026-03-23 05:55:35 UTC

      Identify redundant computations within and across basic blocks using available expression analysis. Replace duplicate expressions with references to the first computation. Use global value numbering (GVN) for cross-block CSE to catch equivalences that simple syntactic matching would miss.

    * ## Ticket: Subtask: Strength reduction {#103}

          status: open
          created: 2026-03-23 05:55:35 UTC
          updated: 2026-03-23 05:55:35 UTC

      Replace expensive operations with cheaper equivalents: multiply by power-of-two becomes shift, division by constant becomes multiply-by-reciprocal using fixed-point magic numbers, modulo by power-of-two becomes bitwise AND. Apply induction variable strength reduction in loops to turn multiplies into incremental adds.

    * ## Ticket: Subtask: Loop-invariant code motion {#104}

          status: open
          created: 2026-03-23 05:55:35 UTC
          updated: 2026-03-23 05:55:35 UTC

      Identify instructions inside loops whose operands do not change across iterations. Hoist them into the loop preheader block. Verify safety by checking that the moved instruction dominates all loop exits or that the instruction has no observable side effects.

  * ## Ticket: Task: Memory optimizations {#18}

        status: open
        created: 2026-03-23 05:41:12 UTC
        updated: 2026-03-23 05:41:12 UTC

    Scalar replacement of aggregates (SROA), load/store forwarding, dead store elimination, alias analysis.

    * ## Ticket: Subtask: Scalar replacement of aggregates (SROA) {#105}

          status: open
          created: 2026-03-23 05:55:44 UTC
          updated: 2026-03-23 05:55:44 UTC

      Break small stack-allocated structs and arrays into individual SSA variables when their address is never taken. Analyze all uses of an alloca to determine if they are field-by-field accesses, then replace the alloca with one SSA variable per field, enabling subsequent register allocation of struct members.

    * ## Ticket: Subtask: Load/store forwarding {#106}

          status: open
          created: 2026-03-23 05:55:44 UTC
          updated: 2026-03-23 05:55:44 UTC

      When a store is followed by a load of the same address with no intervening aliasing writes, replace the load with the stored value directly. Implement must-alias analysis for this purpose, tracking base pointers plus constant offsets to prove address equality without full alias analysis.

    * ## Ticket: Subtask: Dead store elimination {#107}

          status: open
          created: 2026-03-23 05:55:44 UTC
          updated: 2026-03-23 05:55:44 UTC

      Remove store instructions whose stored values are overwritten before any load from that address. Walk each basic block backwards, maintaining a set of live store targets; a store to an already-live target kills the earlier store.

    * ## Ticket: Subtask: Alias analysis framework {#108}

          status: open
          created: 2026-03-23 05:55:44 UTC
          updated: 2026-03-23 05:55:44 UTC

      Implement a points-to analysis to determine whether two memory accesses may, must, or cannot alias. Support type-based alias analysis (TBAA) using C/C++ strict aliasing rules, and field-sensitive analysis for struct members. Provide a query interface used by load/store forwarding, dead store elimination, and code motion passes.

  * ## Ticket: Task: Control flow optimizations {#19}

        status: open
        created: 2026-03-23 05:41:12 UTC
        updated: 2026-03-23 05:41:12 UTC

    Branch folding, block merging, loop unrolling, loop unswitching, tail call optimization.

    * ## Ticket: Subtask: Branch folding and block merging {#109}

          status: open
          created: 2026-03-23 05:55:53 UTC
          updated: 2026-03-23 05:55:53 UTC

      Eliminate unconditional branches to blocks with a single predecessor by merging the blocks. Fold conditional branches on constant conditions into unconditional branches. Remove empty blocks that only contain a jump, redirecting predecessors to the target.

    * ## Ticket: Subtask: Loop unrolling {#110}

          status: open
          created: 2026-03-23 05:55:53 UTC
          updated: 2026-03-23 05:55:53 UTC

      Fully unroll loops with small constant trip counts. For larger loops, apply partial unrolling (2x or 4x) to reduce branch overhead and expose instruction-level parallelism. Use the trip count and loop body size in the cost model to decide the unrolling factor.

    * ## Ticket: Subtask: Tail call optimization {#111}

          status: open
          created: 2026-03-23 05:55:53 UTC
          updated: 2026-03-23 05:55:53 UTC

      Detect tail-position calls where the caller immediately returns the callee's result with no intervening work. Replace the call+ret sequence with a tail-call (jump) that reuses the caller's stack frame. Verify that the callee's argument area fits within the caller's to avoid stack corruption.

  * ## Ticket: Task: Inlining and interprocedural optimization {#20}

        status: open
        created: 2026-03-23 05:41:12 UTC
        updated: 2026-03-23 05:41:12 UTC

    Cost-model-based inlining, dead argument elimination, interprocedural constant propagation. Link-time optimization (LTO) support.

    * ## Ticket: Subtask: Inlining cost model and heuristics {#112}

          status: open
          created: 2026-03-23 05:55:59 UTC
          updated: 2026-03-23 05:55:59 UTC

      Compute an inline cost for each call site based on callee instruction count, number of call sites, constant argument specialization potential, and hot/cold profile data. Apply a threshold that varies by optimization level (-O2 vs -Os). Always inline functions marked `__attribute__((always_inline))` or C++ `inline` with a single call site.

    * ## Ticket: Subtask: Dead argument elimination {#113}

          status: open
          created: 2026-03-23 05:55:59 UTC
          updated: 2026-03-23 05:55:59 UTC

      Identify function parameters that are never used in any call path through the function body. Remove them from the function signature and update all call sites. This reduces register pressure and can enable further optimizations at call sites that were computing now-removed arguments.

    * ## Ticket: Subtask: Interprocedural constant propagation {#114}

          status: open
          created: 2026-03-23 05:55:59 UTC
          updated: 2026-03-23 05:55:59 UTC

      Analyze all call sites of a function to determine if an argument is always the same constant. If so, specialize the function body by substituting the constant and run local optimizations. Create clones for partially-constant call sites rather than modifying the original function.

  * ## Ticket: Task: Vectorization {#21}

        status: open
        created: 2026-03-23 05:41:12 UTC
        updated: 2026-03-23 05:41:12 UTC

    Auto-vectorize inner loops using target vector width. SLP vectorization for straight-line code.

* ## Ticket: Epic: Backend — x86-64 {#22}

      status: open
      created: 2026-03-23 05:41:12 UTC
      updated: 2026-03-23 05:41:12 UTC

  Code generation targeting x86-64 (Linux, macOS, Windows).

  * ## Ticket: Task: Instruction selection {#23}

        status: open
        created: 2026-03-23 05:41:12 UTC
        updated: 2026-03-23 05:41:12 UTC

    Lower IR to x86-64 machine instructions. Pattern matching for complex addressing modes, fused multiply-add, conditional moves.

    * ## Ticket: Subtask: IR-to-MachineIR translation {#115}

          status: open
          created: 2026-03-23 05:56:08 UTC
          updated: 2026-03-23 05:56:08 UTC

      Translate each IR instruction into one or more abstract machine instructions using a SelectionDAG or pattern-matching tree. Lower IR types to x86-64 register classes. Handle legal vs. illegal types by splitting or promoting (e.g., i8 operations promoted to i32).

    * ## Ticket: Subtask: Addressing mode matching {#116}

          status: open
          created: 2026-03-23 05:56:08 UTC
          updated: 2026-03-23 05:56:08 UTC

      Combine base register, index register, scale factor, and displacement into x86-64 addressing modes during instruction selection. Pattern-match sequences like `base + index * scale + offset` to emit a single LEA or memory operand instead of separate add/shift instructions.

    * ## Ticket: Subtask: SIMD and floating-point instruction selection {#117}

          status: open
          created: 2026-03-23 05:56:08 UTC
          updated: 2026-03-23 05:56:08 UTC

      Map IR vector and floating-point operations to SSE/AVX instructions. Select between scalar (ss/sd) and packed (ps/pd) variants. Handle FP-to-integer conversions, rounding modes, and FMA instructions when the target supports them.

    * ## Ticket: Subtask: Intrinsic and builtin lowering {#118}

          status: open
          created: 2026-03-23 05:56:08 UTC
          updated: 2026-03-23 05:56:08 UTC

      Translate compiler intrinsics (__builtin_expect, __builtin_popcount, __builtin_clz, __atomic_*, etc.) into target-specific x86-64 instructions like POPCNT, LZCNT, TZCNT, CMPXCHG, and LOCK-prefixed operations. Fall back to library calls when hardware support is absent.

  * ## Ticket: Task: Register allocation {#24}

        status: open
        created: 2026-03-23 05:41:12 UTC
        updated: 2026-03-23 05:41:12 UTC

    Linear scan or graph coloring allocator. Handle x86-64 register classes (GPR, XMM, YMM). Spill code generation.

    * ## Ticket: Subtask: Liveness analysis {#119}

          status: open
          created: 2026-03-23 05:56:16 UTC
          updated: 2026-03-23 05:56:16 UTC

      Compute live ranges for each virtual register by walking the CFG in reverse. Build live-in and live-out sets per basic block. Detect interference between live ranges that overlap, producing an interference graph used by the register allocator.

    * ## Ticket: Subtask: Register assignment {#120}

          status: open
          created: 2026-03-23 05:56:16 UTC
          updated: 2026-03-23 05:56:16 UTC

      Implement a graph coloring allocator (or linear scan for faster compilation at -O0). Assign physical x86-64 registers to virtual registers while respecting register class constraints. Handle pre-colored registers for ABI-mandated operands like return values in RAX.

    * ## Ticket: Subtask: Spill code generation {#121}

          status: open
          created: 2026-03-23 05:56:16 UTC
          updated: 2026-03-23 05:56:16 UTC

      When no physical register is available, spill a virtual register to a stack slot. Insert store instructions after definitions and load instructions before uses of the spilled value. Apply rematerialization for cheap-to-recompute values (constants, addresses) to avoid memory round-trips.

    * ## Ticket: Subtask: Coalescing and register hints {#122}

          status: open
          created: 2026-03-23 05:56:16 UTC
          updated: 2026-03-23 05:56:16 UTC

      Eliminate unnecessary register-to-register copies by coalescing the source and destination into the same physical register when their live ranges don't interfere. Use register hints from copy instructions and calling conventions to guide allocation toward preferred registers, reducing move instructions in the final output.

  * ## Ticket: Task: Instruction scheduling {#25}

        status: open
        created: 2026-03-23 05:41:12 UTC
        updated: 2026-03-23 05:41:12 UTC

    Reorder instructions to minimize pipeline stalls and maximize instruction-level parallelism.

  * ## Ticket: Task: Machine code emission {#26}

        status: open
        created: 2026-03-23 05:41:12 UTC
        updated: 2026-03-23 05:41:12 UTC

    Encode x86-64 instructions to bytes. REX/VEX prefix handling. Relocations for symbols and branches.

    * ## Ticket: Subtask: Instruction encoding engine {#123}

          status: open
          created: 2026-03-23 05:56:24 UTC
          updated: 2026-03-23 05:56:24 UTC

      Implement the x86-64 variable-length instruction encoder. Handle legacy prefixes, REX prefix generation for 64-bit operands and extended registers, ModR/M and SIB byte computation, and immediate/displacement encoding. Organized as a table-driven encoder with opcode maps for 1/2/3-byte opcodes.

    * ## Ticket: Subtask: VEX/EVEX prefix handling {#124}

          status: open
          created: 2026-03-23 05:56:24 UTC
          updated: 2026-03-23 05:56:24 UTC

      Encode AVX instructions using 2-byte and 3-byte VEX prefixes, and AVX-512 instructions using EVEX prefixes. Handle the vvvv source register field, vector length bit, and mask register encoding. Validate that VEX-encoded instructions cannot be mixed with legacy REX prefixes.

    * ## Ticket: Subtask: Relocation and fixup processing {#125}

          status: open
          created: 2026-03-23 05:56:24 UTC
          updated: 2026-03-23 05:56:24 UTC

      After encoding, resolve branch targets within the same section to relative offsets. Emit relocation entries for cross-section references, external symbol references, and GOT/PLT accesses. Handle relaxation for short vs. near branch encoding by iterating until offsets stabilize.

  * ## Ticket: Task: x86-64 ABI support {#27}

        status: open
        created: 2026-03-23 05:41:12 UTC
        updated: 2026-03-23 05:41:12 UTC

    System V AMD64 ABI (Linux, macOS) and Microsoft x64 ABI (Windows). Struct passing, varargs, stack alignment, exception handling.

    * ## Ticket: Subtask: System V AMD64 calling convention {#126}

          status: open
          created: 2026-03-23 05:56:33 UTC
          updated: 2026-03-23 05:56:33 UTC

      Implement the Linux/macOS calling convention: integer arguments in RDI, RSI, RDX, RCX, R8, R9; FP/vector arguments in XMM0-XMM7; return in RAX/RDX or XMM0/XMM1. Classify struct arguments by eightbyte according to the algorithm in the ABI specification to decide register vs. stack passing.

    * ## Ticket: Subtask: Microsoft x64 calling convention {#127}

          status: open
          created: 2026-03-23 05:56:33 UTC
          updated: 2026-03-23 05:56:33 UTC

      Implement the Windows calling convention: first four arguments in RCX, RDX, R8, R9 (or XMM0-XMM3 for floats); 32-byte shadow space on the stack. Structs of 1, 2, 4, or 8 bytes are passed in a register; larger structs are passed by hidden pointer.

    * ## Ticket: Subtask: Variadic function and stack frame handling {#128}

          status: open
          created: 2026-03-23 05:56:33 UTC
          updated: 2026-03-23 05:56:33 UTC

      Implement varargs support for both ABIs: on System V, save all register arguments to the register save area; on Windows, spill all four register arguments to the shadow space. Ensure 16-byte stack alignment before call instructions by adjusting the prologue.

* ## Ticket: Epic: Backend — ARM64 {#28}

      status: open
      created: 2026-03-23 05:41:12 UTC
      updated: 2026-03-23 05:41:12 UTC

  Code generation targeting AArch64 (Linux, macOS, Android).

  * ## Ticket: Task: ARM64 instruction selection {#29}

        status: open
        created: 2026-03-23 05:41:12 UTC
        updated: 2026-03-23 05:41:12 UTC

    Lower IR to AArch64 instructions. Exploit barrel shifter, conditional select, and load/store pair instructions.

  * ## Ticket: Task: ARM64 register allocation {#30}

        status: open
        created: 2026-03-23 05:41:12 UTC
        updated: 2026-03-23 05:41:12 UTC

    Allocate across 31 GPRs and 32 SIMD/FP registers. Handle callee-saved register conventions.

  * ## Ticket: Task: ARM64 machine code emission {#31}

        status: open
        created: 2026-03-23 05:41:12 UTC
        updated: 2026-03-23 05:41:12 UTC

    Fixed-width 32-bit instruction encoding. PC-relative addressing, ADRP/ADD sequences, branch range relaxation.

  * ## Ticket: Task: ARM64 ABI support {#32}

        status: open
        created: 2026-03-23 05:41:12 UTC
        updated: 2026-03-23 05:41:12 UTC

    AAPCS64 calling convention. HFA/HVA passing rules. Apple ARM64 ABI differences (variadic arguments, tagged pointers).

* ## Ticket: Epic: Object file and linking {#33}

      status: open
      created: 2026-03-23 05:41:12 UTC
      updated: 2026-03-23 05:41:12 UTC

  Emit object files and produce executables or shared libraries.

  * ## Ticket: Task: ELF object file writer {#34}

        status: open
        created: 2026-03-23 05:41:12 UTC
        updated: 2026-03-23 05:41:12 UTC

    Generate ELF relocatable objects for Linux. Sections, symbols, relocations, DWARF debug info references.

    * ## Ticket: Subtask: ELF header and section table {#129}

          status: open
          created: 2026-03-23 05:56:39 UTC
          updated: 2026-03-23 05:56:39 UTC

      Write the ELF64 header with correct e_machine (EM_X86_64 or EM_AARCH64), entry point, and section header table offset. Emit standard sections: .text, .data, .bss, .rodata, .symtab, .strtab, .shstrtab. Compute section sizes and file offsets in a two-pass layout phase.

    * ## Ticket: Subtask: Symbol table emission {#130}

          status: open
          created: 2026-03-23 05:56:39 UTC
          updated: 2026-03-23 05:56:39 UTC

      Build the ELF symbol table (.symtab) with local symbols first, then global symbols, and set the sh_info field to the first global index. Emit the string table (.strtab) with null-terminated symbol names. Handle STB_LOCAL, STB_GLOBAL, STB_WEAK bindings and STT_FUNC, STT_OBJECT types.

    * ## Ticket: Subtask: Relocation records {#131}

          status: open
          created: 2026-03-23 05:56:39 UTC
          updated: 2026-03-23 05:56:39 UTC

      Emit REL or RELA relocation entries for unresolved symbols and PC-relative references. Support R_X86_64_PC32, R_X86_64_PLT32, R_X86_64_64, R_X86_64_GOTPCREL, and the corresponding AArch64 relocation types. Group relocations into per-section .rela.* sections.

    * ## Ticket: Subtask: DWARF debug information references {#132}

          status: open
          created: 2026-03-23 05:56:39 UTC
          updated: 2026-03-23 05:56:39 UTC

      Emit section headers and placeholder content for .debug_info, .debug_abbrev, .debug_line, .debug_str, and .debug_aranges. Generate DWARF line-number programs mapping machine code offsets to source file, line, and column. Integrate with the diagnostic engine's source location tracking.

  * ## Ticket: Task: Mach-O object file writer {#35}

        status: open
        created: 2026-03-23 05:41:12 UTC
        updated: 2026-03-23 05:41:12 UTC

    Generate Mach-O objects for macOS. Segments, sections, relocations, compact unwind info.

  * ## Ticket: Task: PE/COFF object file writer {#36}

        status: open
        created: 2026-03-23 05:41:12 UTC
        updated: 2026-03-23 05:41:12 UTC

    Generate COFF objects for Windows. Sections, symbols, relocations, SEH unwind data.

  * ## Ticket: Task: Linker integration {#37}

        status: open
        created: 2026-03-23 05:41:12 UTC
        updated: 2026-03-23 05:41:12 UTC

    Invoke system linker (ld, lld, link.exe) with correct flags. Library search paths, static/dynamic linking, rpath.

  * ## Ticket: Task: Link-time optimization {#38}

        status: open
        created: 2026-03-23 05:41:12 UTC
        updated: 2026-03-23 05:41:12 UTC

    Serialize IR into object files. At link time, merge modules, run optimization passes, then generate final code.

* ## Ticket: Epic: Diagnostics and tooling {#39}

      status: open
      created: 2026-03-23 05:41:12 UTC
      updated: 2026-03-23 05:41:12 UTC

  Error reporting, warnings, and developer-facing tools.

  * ## Ticket: Task: Diagnostic engine {#40}

        status: open
        created: 2026-03-23 05:41:12 UTC
        updated: 2026-03-23 05:41:12 UTC

    Structured diagnostics with severity, source location, fix-it hints, and note chains. Color terminal output. Machine-readable JSON output.

    * ## Ticket: Subtask: Diagnostic message formatting {#133}

          status: open
          created: 2026-03-23 05:56:46 UTC
          updated: 2026-03-23 05:56:46 UTC

      Format error, warning, and note messages with source file, line, column, severity label, and descriptive text. Render source line excerpts with caret/tilde underlining of the relevant token range. Support ANSI color output for terminals and plain text for non-TTY output.

    * ## Ticket: Subtask: Fix-it hints and note chains {#134}

          status: open
          created: 2026-03-23 05:56:46 UTC
          updated: 2026-03-23 05:56:46 UTC

      Attach machine-applicable fix-it edits (insertions, replacements, removals) to diagnostics. Support note chains that point to related locations (e.g., "previous declaration was here"). Store fix-its as byte-range edits so that IDE integrations can apply them programmatically.

    * ## Ticket: Subtask: Machine-readable diagnostic output {#135}

          status: open
          created: 2026-03-23 05:56:46 UTC
          updated: 2026-03-23 05:56:46 UTC

      Emit diagnostics as structured JSON objects containing file path, line, column, end column, severity, message text, category, and optional fix-its. This format is consumed by IDEs, CI systems, and the static analyzer report viewer.

  * ## Ticket: Task: Warning categories and -W flags {#41}

        status: open
        created: 2026-03-23 05:41:12 UTC
        updated: 2026-03-23 05:41:12 UTC

    Implement -Wall, -Wextra, -Werror, -Wno-*, -Wpedantic. Group warnings into categories. Default warning set per language standard.

  * ## Ticket: Task: Static analyzer {#42}

        status: open
        created: 2026-03-23 05:41:12 UTC
        updated: 2026-03-23 05:41:12 UTC

    Detect use-after-free, null pointer dereference, uninitialized variables, unreachable code, integer overflow. Run as an extra pass with detailed path-sensitive reports.

    * ## Ticket: Subtask: Control flow graph construction for analysis {#136}

          status: open
          created: 2026-03-23 05:56:59 UTC
          updated: 2026-03-23 05:56:59 UTC

      Build an intra-procedural CFG from the AST with explicit join points and exception edges. Annotate each CFG node with the set of variable states (initialized, freed, null, non-null). This CFG is separate from the IR and operates at the source level to produce diagnostics with original variable names.

    * ## Ticket: Subtask: Null pointer dereference detection {#137}

          status: open
          created: 2026-03-23 05:56:59 UTC
          updated: 2026-03-23 05:56:59 UTC

      Track pointer state (null, non-null, maybe-null) through assignments, branches, and function calls. At each dereference, warn if the pointer may be null. Use branch conditions (e.g., `if (p != NULL)`) to refine states along true/false edges and reduce false positives.

    * ## Ticket: Subtask: Use-after-free and double-free detection {#138}

          status: open
          created: 2026-03-23 05:56:59 UTC
          updated: 2026-03-23 05:56:59 UTC

      Model heap object lifecycle through malloc/calloc/realloc/free calls. Track which pointers alias each heap object and mark the object as freed when any alias is passed to free. Flag dereferences of pointers to freed objects and duplicate free calls on already-freed objects.

    * ## Ticket: Subtask: Uninitialized variable detection {#139}

          status: open
          created: 2026-03-23 05:56:59 UTC
          updated: 2026-03-23 05:56:59 UTC

      Track definite-assignment status of local variables across all CFG paths. At each use of a variable, check whether all reaching paths include a definition. Handle partial initialization of struct members and conditionally initialized variables in branches without else clauses.

    * ## Ticket: Subtask: Integer overflow and conversion checks {#140}

          status: open
          created: 2026-03-23 05:56:59 UTC
          updated: 2026-03-23 05:56:59 UTC

      Detect signed integer overflow in arithmetic expressions where operand ranges can be statically bounded. Flag implicit narrowing conversions (e.g., int64 to int32) and sign changes (unsigned to signed) that may lose data. Use value range propagation from loop bounds and comparison guards to reduce false warnings.

  * ## Ticket: Task: Compilation database {#43}

        status: open
        created: 2026-03-23 05:41:12 UTC
        updated: 2026-03-23 05:41:12 UTC

    Emit compile_commands.json for IDE integration. Record exact flags per translation unit.

* ## Ticket: Epic: Build system and testing {#44}

      status: open
      created: 2026-03-23 05:41:12 UTC
      updated: 2026-03-23 05:41:12 UTC

  Build the compiler itself, test suite, and CI.

  * ## Ticket: Task: Build system {#45}

        status: open
        created: 2026-03-23 05:41:12 UTC
        updated: 2026-03-23 05:41:12 UTC

    CMake or Meson build. Build each component as a library. Cross-compilation support. Bootstrap: build the compiler with itself.

    * ## Ticket: Subtask: Build configuration and library structure {#141}

          status: open
          created: 2026-03-23 05:57:03 UTC
          updated: 2026-03-23 05:57:03 UTC

      Set up CMake (or Meson) build with each compiler component (Frontend, IR, Optimizer, Backend, ObjectWriter) as a separate static library. Define proper inter-library dependencies so incremental builds recompile only affected components.

    * ## Ticket: Subtask: Cross-compilation and bootstrap {#142}

          status: open
          created: 2026-03-23 05:57:03 UTC
          updated: 2026-03-23 05:57:03 UTC

      Support cross-compilation by separating host tools from target-dependent code. Implement a bootstrap build mode that compiles the compiler with itself in three stages: stage 1 (host compiler), stage 2 (self-compiled), stage 3 (verify reproducibility by diffing stage 2 and stage 3 binaries).

  * ## Ticket: Task: Test suite infrastructure {#46}

        status: open
        created: 2026-03-23 05:41:12 UTC
        updated: 2026-03-23 05:41:12 UTC

    Lit-style test runner. FileCheck-style output matching. Test categories: lexer, parser, sema, codegen, end-to-end. Regression test for every bug fix.

    * ## Ticket: Subtask: Test runner framework {#143}

          status: open
          created: 2026-03-23 05:57:09 UTC
          updated: 2026-03-23 05:57:09 UTC

      Build a lit-style test runner that discovers test files by directory convention, extracts RUN lines from comments, executes them, and reports pass/fail/xfail. Support parallel test execution, test timeouts, and filtering by test name or directory.

    * ## Ticket: Subtask: FileCheck-style output matching {#144}

          status: open
          created: 2026-03-23 05:57:09 UTC
          updated: 2026-03-23 05:57:09 UTC

      Implement a pattern matcher that verifies compiler output against CHECK, CHECK-NEXT, CHECK-NOT, CHECK-DAG, and CHECK-LABEL directives embedded in test files. Support regex captures and variable substitutions to match dynamic values like register names or line numbers.

    * ## Ticket: Subtask: Test categories and regression tracking {#145}

          status: open
          created: 2026-03-23 05:57:09 UTC
          updated: 2026-03-23 05:57:09 UTC

      Organize tests into categories (lexer, parser, sema, IR, codegen, end-to-end) with separate test directories. Mandate that every bug fix includes a regression test. Provide a summary report showing pass/fail counts per category and comparison against the previous run.

  * ## Ticket: Task: Conformance test suites {#47}

        status: open
        created: 2026-03-23 05:41:12 UTC
        updated: 2026-03-23 05:41:12 UTC

    Run against C11 conformance tests. Run against C++ standard test suites. Track pass/fail rates over time.

  * ## Ticket: Task: Performance benchmarks {#48}

        status: open
        created: 2026-03-23 05:41:12 UTC
        updated: 2026-03-23 05:41:12 UTC

    Compile-time benchmarks (lines/second, memory usage). Generated code benchmarks (SPEC-like). Regression tracking dashboard.

  * ## Ticket: Task: CI/CD pipeline {#49}

        status: open
        created: 2026-03-23 05:41:12 UTC
        updated: 2026-03-23 05:41:12 UTC

    Build and test on Linux, macOS, Windows. Test both debug and release. Nightly bootstrap build. Artifact publishing.

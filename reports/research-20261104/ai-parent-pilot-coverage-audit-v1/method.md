Post-hoc screen after a separate reviewer discovered nested-class global binding omissions
in the frozen checker. For each of the 36 sealed cases, verify source SHA-256, parse
its complete UTF-8 module with CPython ast, walk every AST scope, and list ast.Global
nodes containing the exact case subject name. This conservative whole-tree screen
finds zero such declarations. The known example therefore cannot occur in these
36 supplied sources. This does not establish absence of other shared errors.
Original v1 reference and AI records are preserved unchanged.

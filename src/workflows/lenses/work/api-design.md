<!-- lens: work/api-design v1 -->

# API design

Design the shape of what other code will call: names, contract
closedness, error surfaces, and the difference between an interface
that is easy to use correctly and one that is easy to misuse.

## Targets

- Names that don't match existing conventions in the surrounding
  code, or that require reading the implementation to disambiguate.
- Open contracts where a closed one was possible — unknown fields,
  extra arguments, or unrecognized values accepted silently.
- Error surfaces that are an afterthought: a caller's mistake surfaces
  as an unrelated exception deep in unrelated logic instead of a
  specific, named failure at the boundary.
- Boolean or stringly-typed parameters standing in for what should be
  a named enum or a separate parameter, inviting a call-site mix-up.
- Surface area exposed beyond what the current contract requires a
  caller to set.

## Method

1. List every new or changed public symbol the contract introduces:
   function signatures, schema fields, CLI flags, config keys,
   endpoint shapes.
2. Before naming anything, read two or three neighboring modules or
   schemas already in the codebase and match their conventions. Do
   not introduce a new naming style for one new surface.
3. Decide, and write down, what is required versus optional, what
   default values apply, and whether the contract is closed (rejects
   unknown fields or values) or intentionally open — closed is the
   default; open needs a stated reason.
4. Design the error surface before writing the happy path: what does
   an incorrect call produce, and where does the caller see it
   (exception type, error field, status code)? Prefer a mistake that
   is caught by a type checker or schema over one caught by a runtime
   crash in unrelated code.
5. Construct at least one plausible incorrect usage of the new
   surface and verify it is either statically prevented or fails
   loudly and specifically at the boundary, not silently or deep
   inside.
6. Replace boolean or stringly-typed flags with a named enum or a
   separate parameter wherever the values are not truly
   interchangeable — the same type-conflation class the defect
   taxonomy tracks, applied at design time instead of found later.
7. Keep the surface minimal: do not add a parameter, field, or option
   the current contract does not require a caller to set. Extra
   surface is a maintenance and misuse cost, not a convenience.
8. Record the finalized signature or schema alongside any rejected
   alternative, with a one-line reason it was rejected.

## Does not cover

- Whether the internal behavior behind the interface matches the
  contract — that is `work/spec-fidelity`.
- How much existing code had to change to introduce the interface —
  that is `work/minimal-change`.
- What happens at runtime when malformed data actually reaches this
  interface — that is `work/defensive-input`. This lens decides the
  shape of validation and errors; defensive-input decides the
  behavior for the bad data itself.

## Output obligations

- The list of new or changed public symbols with their final
  signature or schema.
- The rejected alternative(s) considered for each, with a one-line
  reason.
- A documented error surface: what a caller sees for each plausible
  misuse, referenced in `evidence_refs`.
- Any deviation from existing repo naming or idiom conventions,
  recorded with its reason.

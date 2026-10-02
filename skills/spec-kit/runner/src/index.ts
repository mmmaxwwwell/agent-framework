/**
 * @spec-kit/runner — TypeScript port of the spec-kit parallel runner.
 *
 * Entry point. Wiring (Supervisor → Developers → roles) lands in M1; this is
 * the M0 stub so the package builds and `npm run dev` has a target.
 */

export const RUNNER_NAME = "@spec-kit/runner";

function main(): void {
  console.log(`${RUNNER_NAME}: not yet implemented`);
}

main();

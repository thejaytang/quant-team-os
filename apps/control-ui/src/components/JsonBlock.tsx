export function JsonBlock({ value }: { value: unknown }) {
  return <pre className="qto-json">{JSON.stringify(value ?? {}, null, 2)}</pre>;
}

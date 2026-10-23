'use strict';
const fs = require('node:fs');
const ts = require(process.argv[2]);
if (process.versions.node.split('.')[0] !== '24' || ts.version !== '6.0.3') {
  throw new Error('Expected Node 24 and TypeScript 6.0.3');
}
const values = JSON.parse(fs.readFileSync(0, 'utf8'));
function syntax(node) {
  if (!node) return null;
  const result = [ts.SyntaxKind[node.kind]];
  const children = node.getChildren();
  if (!children.length) result.push(node.getText());
  result.push(...children.map(syntax));
  return result;
}
function canonical(value) {
  const s = value.signature;
  const parameters = s.parameters.map(p =>
    `${p.rest ? '...' : ''}${p.pattern}${p.optional ? '?' : ''}` +
    `${p.annotation === null ? '' : ': ' + p.annotation}` +
    `${p.default === null ? '' : ' = ' + p.default}`).join(', ');
  const source = `${s.async ? 'async ' : ''}function ${s.generator ? '*' : ''}__cami` +
    `${s.type_parameters.length ? '<' + s.type_parameters.join(', ') + '>' : ''}` +
    `(${parameters})${s.return_annotation === null ? '' : ': ' + s.return_annotation} {}`;
  const parse = text => ts.createSourceFile('signature.' + value.language, text,
    ts.ScriptTarget.Latest, true,
    ['tsx', 'jsx'].includes(value.language) ? ts.ScriptKind.TSX : ts.ScriptKind.TS);
  let parsed = parse(source);
  if (parsed.parseDiagnostics.length) return null;
  // The compiler removes trivia before token traversal, including attached JSDoc.
  parsed = parse(ts.createPrinter({removeComments: true}).printFile(parsed));
  if (parsed.parseDiagnostics.length || parsed.statements.length !== 1) return null;
  const node = parsed.statements[0];
  if (!ts.isFunctionDeclaration(node) || node.parameters.length !== s.parameters.length ||
      !node.body || node.body.statements.length) return null;
  const encode = n => n ? JSON.stringify(syntax(n)) : null;
  return {
    format: 'ecma.syntax-signature/2',
    parameters: node.parameters.map((p, i) => ({
      pattern: encode(p.name), optional: s.parameters[i].optional, rest: s.parameters[i].rest,
      default: encode(p.initializer), annotation: encode(p.type),
    })),
    type_parameters: (node.typeParameters || []).map(encode),
    return_annotation: encode(node.type), is_async: s.async, generator: s.generator,
  };
}
process.stdout.write(JSON.stringify(values.map(canonical)));

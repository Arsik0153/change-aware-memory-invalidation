'use strict';

const path = require('node:path').posix;
const crypto = require('node:crypto');
const fs = require('node:fs');
// An absolute dependency path prevents Node's ancestor/global module lookup.
if (!process.argv[2] || !require('node:path').isAbsolute(process.argv[2])) {
  throw new Error('CAMI launcher must supply an absolute trusted compiler path');
}
if (process.versions.node.split('.')[0] !== '24') throw new Error('CAMI requires Node.js 24');
const ts = require(process.argv[2]);
if (ts.version !== '6.0.3') throw new Error('CAMI requires typescript 6.0.3');
const ROOT = '/__cami_snapshot__';
const hash = value => crypto.createHash('sha256').update(value).digest('hex');
const order = (a, b) => {
  const left = JSON.stringify(a), right = JSON.stringify(b);
  return left < right ? -1 : left > right ? 1 : 0;
};
const has = (node, kind) => node.modifiers?.some(m => m.kind === kind) || false;
const isFunction = node => ts.isFunctionDeclaration(node) || ts.isFunctionExpression(node) ||
  ts.isArrowFunction(node) || ts.isMethodDeclaration(node) || ts.isGetAccessor(node) ||
  ts.isSetAccessor(node) || ts.isConstructorDeclaration(node);
const isCode = name => ['.js', '.jsx', '.ts', '.tsx'].some(ext => name.endsWith(ext));
const declarationFile = name => name.endsWith('.d.ts');

/** @typedef {{kind: 'known', name: string} | {kind: 'dynamic'}} MemberIdentity */

/**
 * @param {import('typescript').PropertyName} node
 * @returns {MemberIdentity}
 */
function memberIdentity(node) {
  if (ts.isIdentifier(node) || ts.isPrivateIdentifier(node)) {
    return {kind: 'known', name: node.text};
  }
  const key = ts.isComputedPropertyName(node) ? node.expression : node;
  if (!ts.isStringLiteral(key) && !ts.isNumericLiteral(key)) return {kind: 'dynamic'};
  const value = ts.isNumericLiteral(key) ? String(Number(key.text)) : key.text;
  // Quote non-segments so public "#x" and "a.b" cannot alias private/nested names.
  const name = ts.isIdentifierText(value, ts.ScriptTarget.Latest) || /^(0|[1-9][0-9]*)$/.test(value)
    ? value : JSON.stringify(value);
  return {kind: 'known', name};
}

function analyze(request) {
  if (request.schema_version !== 1 || typeof request.request_id !== 'string' ||
      !request.files || typeof request.files !== 'object' || Array.isArray(request.files)) {
    throw new Error('invalid request');
  }
  const validPath = name => typeof name === 'string' && name.length > 0 && name.length <= 4096 &&
    !name.includes(':') && !name.includes('\\') && ![...name].some(c => c.charCodeAt(0) < 32) &&
    !name.split('/').some(p => p === '' || p === '..' || p === '.' || p === 'node_modules');
  if (!request.request_id || request.request_id.length > 1024 ||
      Object.keys(request.files).length > 10000 ||
      (request.root_config !== undefined && request.root_config !== null && !validPath(request.root_config))) {
    throw new Error('invalid request limits or root config');
  }
  const files = new Map();
  for (const [name, source] of Object.entries(request.files).sort()) {
    if (typeof source !== 'string' || !validPath(name)) {
      throw new Error('invalid captured path or source');
    }
    files.set(`${ROOT}/${name}`, source);
  }
  const relative = name => name.startsWith(`${ROOT}/`) ? name.slice(ROOT.length + 1) : null;
  const read = name => files.get(path.normalize(name));
  const directories = new Set([ROOT]);
  for (const name of files.keys()) {
    let directory = path.dirname(name);
    while (directory.startsWith(ROOT)) {
      directories.add(directory);
      if (directory === ROOT) break;
      directory = path.dirname(directory);
    }
  }
  const diagnostics = [];
  const definitions = [];
  const identityGaps = [];
  function identityGap(node, qualname, descendants, reason,
    nodeKinds = ['function', 'arrow', 'function_expression', 'method']) {
    identityGaps.push({path: relative(node.getSourceFile().fileName), qualname, descendants,
      node_kinds: nodeKinds, reason});
  }
  const relations = [];
  const unresolved = [];
  const exports = [];
  const excluded = [];
  const sources = new Map();
  const modules = new Map();
  const nodeScopes = new Map();
  const allBindings = [];
  const site = node => {
    const sf = node.getSourceFile();
    const start = node.getStart(sf);
    const end = node.end;
    const begin = sf.getLineAndCharacterOfPosition(start);
    const finish = sf.getLineAndCharacterOfPosition(end);
    return {path: relative(sf.fileName), start, end, line: begin.line + 1,
      column: begin.character + 1, end_line: finish.line + 1, end_column: finish.character + 1};
  };
  function diagnostic(code, message, severity = 'error', evidence = null) {
    diagnostics.push({code: String(code), message, severity, site: evidence});
  }
  function compilerDiagnostic(d) {
    let evidence = null;
    if (d.file && d.start !== undefined) {
      const begin = d.file.getLineAndCharacterOfPosition(d.start);
      const end = d.start + (d.length || 0);
      const finish = d.file.getLineAndCharacterOfPosition(end);
      evidence = {path: relative(d.file.fileName), start: d.start, end,
        line: begin.line + 1, column: begin.character + 1,
        end_line: finish.line + 1, end_column: finish.character + 1};
    }
    diagnostic(`TS${d.code}`, ts.flattenDiagnosticMessageText(d.messageText, '\n'),
      d.category === ts.DiagnosticCategory.Error ? 'error' : 'warning', evidence);
  }
  const virtualHost = {
    fileExists: name => files.has(path.normalize(name)), readFile: read,
    directoryExists: name => directories.has(path.normalize(name)),
    getDirectories: name => [...directories].filter(d => path.dirname(d) === name),
    readDirectory: () => [...files.keys()].filter(isCode),
    realpath: name => path.normalize(name), useCaseSensitiveFileNames: true,
    getCurrentDirectory: () => ROOT,
    onUnRecoverableConfigFileDiagnostic: compilerDiagnostic,
  };
  let rootConfig = request.root_config;
  if (rootConfig === null || rootConfig === undefined) {
    rootConfig = ['tsconfig.json', 'jsconfig.json'].find(p => files.has(`${ROOT}/${p}`)) || null;
  }
  let configValid = true;
  const checkedConfigs = new Set();
  function checkConfig(name, stack = []) {
    if (stack.includes(name) || stack.length >= 16) {
      diagnostic('config_cycle_or_depth', 'Config extends cycle or depth exceeds 16');
      configValid = false;
      return;
    }
    if (checkedConfigs.has(name)) return;
    const text = read(name);
    if (text === undefined) {
      diagnostic('missing_config', `Captured config is missing: ${relative(name) || name}`);
      configValid = false;
      return;
    }
    const parsed = ts.parseConfigFileTextToJson(name, text);
    if (parsed.error) { compilerDiagnostic(parsed.error); configValid = false; return; }
    const config = parsed.config;
    if (!config || typeof config !== 'object' || Array.isArray(config)) {
      diagnostic('invalid_config', 'Config must be a JSON object'); configValid = false; return;
    }
    if (config.references) {
      diagnostic('project_references_unsupported', 'Project references are not analyzed');
      configValid = false;
    }
    const bases = typeof config.extends === 'string' ? [config.extends] : config.extends || [];
    if (!Array.isArray(bases)) {
      diagnostic('invalid_extends', 'Config extends must be a string or array'); configValid = false;
    } else for (const base of bases) {
      if (typeof base !== 'string' || !base.startsWith('.') || base.includes('\\')) {
        diagnostic('external_extends', 'Only captured relative config extends are supported');
        configValid = false; continue;
      }
      let target = path.resolve(path.dirname(name), base);
      if (!target.endsWith('.json')) target += '.json';
      if (!relative(target)) {
        diagnostic('config_escape', 'Config extends escapes captured root'); configValid = false;
      } else checkConfig(target, [...stack, name]);
    }
    checkedConfigs.add(name);
  }
  let options = {module: ts.ModuleKind.ESNext, moduleResolution: ts.ModuleResolutionKind.Bundler};
  if (rootConfig) {
    checkConfig(`${ROOT}/${rootConfig}`);
    if (configValid) {
      const parsed = ts.getParsedCommandLineOfConfigFile(`${ROOT}/${rootConfig}`, {}, virtualHost);
      if (!parsed) configValid = false;
      else {
        parsed.errors.filter(d => d.code !== 18003).forEach(compilerDiagnostic);
        if (parsed.errors.some(d => d.category === ts.DiagnosticCategory.Error && d.code !== 18003)) {
          configValid = false;
        }
        options = {...options, ...Object.fromEntries(Object.entries(parsed.options).filter(([, value]) => value !== undefined))};
      }
    }
  } else diagnostic('default_module_mode', 'No root config; CAMI assumes ESNext and bundler resolution', 'info');
  const configuration = {
    root_config: rootConfig, valid: configValid,
    module: ts.ModuleKind[options.module], module_resolution: ts.ModuleResolutionKind[options.moduleResolution],
    fingerprint: hash(JSON.stringify({rootConfig, options, compiler: ts.version,
      configs: [...files].filter(([p]) => p.endsWith('.json'))})),
  };
  const caseGroups = new Map();
  for (const name of files.keys()) {
    const key = name.toLowerCase();
    if (!caseGroups.has(key)) caseGroups.set(key, []);
    caseGroups.get(key).push(name);
  }
  for (const [name, text] of files) {
    if (!isCode(name)) continue;
    if (declarationFile(name)) { excluded.push({path: relative(name), reason: 'declaration_file'}); continue; }
    if (caseGroups.get(name.toLowerCase()).length > 1) {
      excluded.push({path: relative(name), reason: 'case_collision'});
      diagnostic('case_collision', `Case-colliding captured source: ${relative(name)}`); continue;
    }
    sources.set(name, ts.createSourceFile(name, text, {languageVersion: ts.ScriptTarget.Latest,
      impliedNodeFormat: ts.getImpliedNodeFormatForFile(name, undefined, virtualHost, options)}, true));
  }
  const compilerHost = {...virtualHost, useCaseSensitiveFileNames: () => true,
    getSourceFile: name => sources.get(path.normalize(name)),
    getDefaultLibFileName: () => `${ROOT}/__no_lib__.d.ts`,
    getCanonicalFileName: name => name, getNewLine: () => '\n', writeFile: () => {},
  };
  const program = ts.createProgram([...sources.keys()], {...options, allowJs: true, noLib: true,
    noResolve: true, noEmit: true, jsx: ts.JsxEmit.Preserve}, compilerHost);
  for (const [name, sf] of sources) {
    const errors = program.getSyntacticDiagnostics(sf);
    errors.forEach(compilerDiagnostic);
    if (errors.length) { excluded.push({path: relative(name), reason: 'syntax_error'}); continue; }
    modules.set(name, {sf, scope: null, exports: new Map(), sideEffects: []});
  }
  function scope(parent, node, owner, kind) {
    return {parent, owner, kind, qualname: parent?.qualname || '', bindings: new Map(), id: `${relative(node.getSourceFile().fileName)}:${node.pos}:${kind}`};
  }
  function bind(s, name, entry) {
    if (!s.bindings.has(name)) {
      const b = {name, scope: s, entries: [], writes: false};
      s.bindings.set(name, b); allBindings.push(b);
    }
    s.bindings.get(name).entries.push(entry);
  }
  function bindingNames(node, visit) {
    if (ts.isIdentifier(node)) visit(node.text);
    else if (ts.isObjectBindingPattern(node) || ts.isArrayBindingPattern(node)) {
      for (const element of node.elements) if (ts.isBindingElement(element)) bindingNames(element.name, visit);
    }
  }
  function nearestFunction(s) {
    while (s.parent && s.kind !== 'function' && s.kind !== 'module') s = s.parent;
    return s;
  }
  function lookup(s, name) {
    while (s) {
      if (s.bindings.has(name)) return s.bindings.get(name);
      s = s.parent;
    }
    return null;
  }
  function addExport(module, name, value) {
    if (!module.exports.has(name)) module.exports.set(name, []);
    module.exports.get(name).push(value);
  }
  function astDigest(node) {
    const parts = [];
    function walk(n) {
      parts.push(n.kind);
      const children = [];
      ts.forEachChild(n, child => { children.push(child); });
      if (!children.length) parts.push(n.getText());
      children.forEach(walk);
    }
    walk(node);
    return hash(JSON.stringify(parts));
  }
  function definition(node, name, kind, parent, conditional) {
    const evidence = site(node);
    const qualname = parent ? `${parent}.${name}` : name;
    const id = `${evidence.path}:${evidence.start}:${kind}`;
    const signature = {
      parameters: node.parameters.map(p => ({pattern: p.name.getText(), optional: !!p.questionToken,
        rest: !!p.dotDotDotToken, default: p.initializer?.getText() || null,
        annotation: p.type?.getText() || null})),
      type_parameters: node.typeParameters?.map(p => p.getText()) || [],
      return_annotation: node.type?.getText() || null,
      async: has(node, ts.SyntaxKind.AsyncKeyword), generator: !!node.asteriskToken,
    };
    const d = {id, key: {path: evidence.path, qualname, kind}, name,
      language: path.extname(evidence.path).slice(1), site: evidence, signature,
      syntax_hash: hash(node.getText()), ast_hash: astDigest(node), ambiguous: conditional,
      implementation: !!node.body};
    definitions.push(d);
    return d;
  }
  function collect(node, s, module, parentName = '', conditional = false) {
    nodeScopes.set(node, s);
    if (ts.isImportDeclaration(node)) {
      const clause = node.importClause;
      const specifier = node.moduleSpecifier.text;
      if (!clause) module.sideEffects.push(node);
      function imported(name, exported, typeOnly, namespace = false) {
        bind(s, name, {kind: 'import', module, specifier, exported, typeOnly, namespace,
          node, initialization: 0});
      }
      if (clause?.name) imported(clause.name.text, 'default', !!clause.isTypeOnly);
      if (clause?.namedBindings) {
        if (ts.isNamespaceImport(clause.namedBindings)) imported(clause.namedBindings.name.text, '*', !!clause.isTypeOnly, true);
        else for (const element of clause.namedBindings.elements) {
          imported(element.name.text, (element.propertyName || element.name).text,
            !!clause.isTypeOnly || !!element.isTypeOnly);
        }
      }
      return;
    }
    if (ts.isImportEqualsDeclaration(node)) {
      bind(s, node.name.text, {kind: 'unknown', reason: 'commonjs_unsupported', node});
      return;
    }
    if (ts.isExportDeclaration(node)) {
      const specifier = node.moduleSpecifier?.text || null;
      if (node.exportClause && ts.isNamedExports(node.exportClause)) {
        for (const element of node.exportClause.elements) addExport(module, element.name.text,
          {kind: specifier ? 'reexport' : 'local', specifier,
            name: (element.propertyName || element.name).text,
            typeOnly: !!node.isTypeOnly || !!element.isTypeOnly, node: element});
      } else {
        addExport(module, '*', {kind: 'unsupported', reason: 'export_star_unsupported', node,
          typeOnly: !!node.isTypeOnly});
      }
      return;
    }
    if (ts.isExportAssignment(node)) {
      if (node.isExportEquals || !isFunction(node.expression)) {
        identityGap(node, '<default>', true, 'export_expression_unsupported');
      }
      if (!node.isExportEquals && ts.isIdentifier(node.expression)) {
        addExport(module, 'default', {kind: 'local', name: node.expression.text, typeOnly: false, node});
      } else if (!node.isExportEquals && isFunction(node.expression)) {
        const d = collectFunction(node.expression, s, module, '<default>',
          ts.isArrowFunction(node.expression) ? 'arrow' : 'function_expression', parentName, conditional);
        addExport(module, 'default', {kind: 'definition', definition: d, node, typeOnly: false});
      } else {
        addExport(module, 'default', {kind: 'unsupported', reason: 'export_expression_unsupported', node, typeOnly: false});
        collect(node.expression, s, module, parentName, conditional);
      }
      return;
    }
    if (ts.isVariableDeclaration(node)) {
      if (ts.isCatchClause(node.parent)) {
        collect(node.name, s, module, parentName, conditional);
        return;
      }
      const target = (node.parent.flags & ts.NodeFlags.BlockScoped) ? s : nearestFunction(s);
      const simpleFunction = ts.isIdentifier(node.name) && node.initializer &&
        (ts.isArrowFunction(node.initializer) || ts.isFunctionExpression(node.initializer));
      let d = null;
      if (simpleFunction) d = collectFunction(node.initializer, s, module, node.name.text,
        ts.isArrowFunction(node.initializer) ? 'arrow' : 'function_expression', parentName, conditional);
      bindingNames(node.name, name => bind(target, name, d ?
        {kind: 'definition', definition: d, node, initialization: node.end, conditional} :
        {kind: 'unknown', reason: 'unsupported_binding', node}));
      const statement = node.parent.parent;
      if (has(statement, ts.SyntaxKind.ExportKeyword)) bindingNames(node.name, name => {
        addExport(module, name, {kind: 'local', name, node, typeOnly: false});
      });
      collect(node.name, s, module, parentName, conditional);
      if (node.initializer && !simpleFunction) collect(node.initializer, s, module, parentName, conditional);
      return;
    }
    if (ts.isFunctionDeclaration(node)) {
      const name = node.name?.text || '<default>';
      const d = collectFunction(node, s, module, name, 'function', parentName, conditional);
      if (node.name) bind(s, name, {kind: 'definition', definition: d, node, initialization: 0, conditional});
      if (has(node, ts.SyntaxKind.ExportKeyword)) addExport(module,
        has(node, ts.SyntaxKind.DefaultKeyword) ? 'default' : name,
        {kind: 'definition', definition: d, node, typeOnly: false});
      return;
    }
    if (isFunction(node)) {
      const identity = node.name ? memberIdentity(node.name) : {kind: 'dynamic'};
      if (ts.isMethodDeclaration(node) && identity.kind === 'known') {
        collectFunction(node, s, module, identity.name, 'method', parentName, conditional);
      }
      else {
        if (ts.isMethodDeclaration(node) || ts.isGetAccessorDeclaration(node) || ts.isSetAccessorDeclaration(node)) {
          const name = identity.kind === 'known' ? identity.name : null;
          identityGap(node, name ? (parentName ? `${parentName}.${name}` : name) : parentName,
            true, 'computed_or_accessor_identity', name ? undefined : ['method']);
        }
        collectFunction(node, s, module, null, null, parentName, conditional);
      }
      return;
    }
    if (ts.isPropertyDeclaration(node) || ts.isPropertyAssignment(node) || ts.isShorthandPropertyAssignment(node)) {
      const identity = memberIdentity(node.name);
      if (identity.kind === 'dynamic') {
        identityGap(node, parentName, true, 'computed_property_identity', ['method']);
      } else {
        identityGap(node, parentName ? `${parentName}.${identity.name}` : identity.name,
          true, 'unsupported_property_binding');
      }
    }
    if (ts.isClassDeclaration(node) || ts.isClassExpression(node)) {
      if (ts.isClassDeclaration(node) && node.name) bind(s, node.name.text,
        {kind: 'unknown', reason: 'class_dispatch_unsupported', node});
      const classScope = scope(s, node, s.owner, 'class');
      nodeScopes.set(node, classScope);
      const className = node.name?.text || '<class>';
      classScope.qualname = parentName ? `${parentName}.${className}` : className;
      if (node.name) bind(classScope, node.name.text,
        {kind: 'unknown', reason: 'class_dispatch_unsupported', node});
      ts.forEachChild(node, child => collect(child, classScope, module,
        parentName ? `${parentName}.${className}` : className, conditional));
      return;
    }
    if (ts.isWithStatement(node)) {
      s = scope(s, node, s.owner, 'dynamic');
      s.dynamic = true;
      nodeScopes.set(node, s);
      diagnostic('dynamic_scope_unsupported', 'With statement prevents lexical resolution', 'warning', site(node));
    }
    if (ts.isBlock(node) || ts.isCatchClause(node) || ts.isForStatement(node) ||
        ts.isForInStatement(node) || ts.isForOfStatement(node) || ts.isCaseBlock(node)) {
      s = scope(s, node, s.owner, 'block');
      nodeScopes.set(node, s);
      if (ts.isCatchClause(node) && node.variableDeclaration) {
        bindingNames(node.variableDeclaration.name, name => bind(s, name,
          {kind: 'unknown', reason: 'catch_binding', node}));
      }
    }
    if (ts.isEnumDeclaration(node) || ts.isModuleDeclaration(node)) {
      if (node.name && ts.isIdentifier(node.name)) bind(s, node.name.text,
        {kind: 'unknown', reason: 'namespace_or_enum_unsupported', node});
      identityGap(node, parentName ? `${parentName}.${node.name.text}` : node.name.text, true,
        'namespace_or_enum_unsupported');
      diagnostic('namespace_or_enum_unsupported', 'Namespace and enum bodies are excluded', 'warning', site(node));
      return;
    }
    const branch = conditional || ts.isIfStatement(node) || ts.isConditionalExpression(node) ||
      ts.isSwitchStatement(node) || ts.isIterationStatement(node, false) || ts.isTryStatement(node);
    ts.forEachChild(node, child => collect(child, s, module, parentName, branch));
  }
  function collectFunction(node, enclosing, module, name, kind, parentName, conditional) {
    const d = name ? definition(node, name, kind, parentName, conditional) : null;
    const s = scope(enclosing, node, d?.id || null, 'function');
    nodeScopes.set(node, s);
    if (ts.isFunctionExpression(node) && node.name) bind(s, node.name.text,
      d ? {kind: 'definition', definition: d, node, initialization: 0, conditional} :
        {kind: 'unknown', reason: 'anonymous_function', node});
    if (!ts.isArrowFunction(node)) bind(s, 'arguments',
      {kind: 'unknown', reason: 'implicit_arguments_binding', node});
    for (const parameter of node.parameters) {
      if (ts.isConstructorDeclaration(node) && ts.isParameterPropertyDeclaration(parameter, node)) {
        bindingNames(parameter.name, name => identityGap(parameter, `${parentName}.${name}`,
          true, 'parameter_property_unsupported', ['method']));
      }
      bindingNames(parameter.name, n => bind(s, n, {kind: 'unknown', reason: 'parameter_binding', node: parameter}));
    }
    const nextName = d?.key.qualname || `${parentName ? `${parentName}.` : ''}<callback@${node.getStart()}>`;
    s.qualname = nextName;
    ts.forEachChild(node, child => {
      const environment = child === node.body ? scope(s, child, s.owner, 'function') : s;
      collect(child, environment, module, nextName, false);
    });
    return d;
  }
  for (const module of modules.values()) {
    module.scope = scope(null, module.sf, null, 'module');
    collect(module.sf, module.scope, module);
  }
  function markWrite(node, s) {
    if (ts.isIdentifier(node)) { const b = lookup(s, node.text); if (b) b.writes = true; }
    else if (ts.isPropertyAccessExpression(node) || ts.isElementAccessExpression(node)) markWrite(node.expression, s);
    else if (ts.isObjectLiteralExpression(node)) {
      for (const p of node.properties) {
        if (ts.isShorthandPropertyAssignment(p)) markWrite(p.name, s);
        else if (ts.isPropertyAssignment(p)) markWrite(p.initializer, s);
        else if (ts.isSpreadAssignment(p)) markWrite(p.expression, s);
      }
    } else if (ts.isArrayLiteralExpression(node)) node.elements.forEach(n => markWrite(n, s));
    else if (ts.isParenthesizedExpression(node) || ts.isSpreadElement(node) || ts.isAsExpression(node) ||
        ts.isTypeAssertionExpression(node) || ts.isNonNullExpression(node) || ts.isSatisfiesExpression(node)) markWrite(node.expression, s);
    else if (ts.isBinaryExpression(node)) markWrite(node.left, s);
  }
  function writes(node, s) {
    s = nodeScopes.get(node) || s;
    if (ts.isEnumDeclaration(node) || ts.isModuleDeclaration(node)) return;
    if (ts.isCallExpression(node) && ts.isIdentifier(node.expression) &&
        node.expression.text === 'eval' && !lookup(s, 'eval')) {
      nearestFunction(s).dynamic = true;
      diagnostic('dynamic_scope_unsupported', 'Direct eval prevents lexical resolution in this function scope', 'warning', site(node));
    }
    if (ts.isBinaryExpression(node) && node.operatorToken.kind >= ts.SyntaxKind.FirstAssignment &&
        node.operatorToken.kind <= ts.SyntaxKind.LastAssignment) markWrite(node.left, s);
    if ((ts.isPrefixUnaryExpression(node) || ts.isPostfixUnaryExpression(node)) &&
        (node.operator === ts.SyntaxKind.PlusPlusToken || node.operator === ts.SyntaxKind.MinusMinusToken)) markWrite(node.operand, s);
    if (ts.isDeleteExpression(node)) markWrite(node.expression, s);
    if ((ts.isForInStatement(node) || ts.isForOfStatement(node)) && !ts.isVariableDeclarationList(node.initializer)) {
      markWrite(node.initializer, s);
    }
    ts.forEachChild(node, child => writes(child, s));
  }
  for (const module of modules.values()) writes(module.sf, module.scope);
  const keys = new Map();
  for (const d of definitions) {
    const key = JSON.stringify(d.key);
    if (!keys.has(key)) keys.set(key, []);
    keys.get(key).push(d);
  }
  for (const group of keys.values()) if (group.length > 1) group.forEach(d => { d.ambiguous = true; });
  for (const b of allBindings) if (b.writes || b.entries.length > 1) {
    b.entries.forEach(e => { if (e.definition) e.definition.ambiguous = true; });
  }
  for (const b of allBindings) {
    for (const entry of b.entries) if (entry.kind !== 'definition') {
      identityGap(entry.node, b.scope.qualname ? `${b.scope.qualname}.${b.name}` : b.name,
        entry.reason !== 'class_dispatch_unsupported', entry.reason || 'unsupported_binding');
    }
  }
  const failure = (reason, candidates = []) => ({reason, candidates: [...new Set(candidates)].sort()});
  const success = d => d.ambiguous || !d.implementation ? failure('ambiguous_declaration', [d.id]) :
    {reason: null, candidates: [d.id]};
  function resolveModule(module, specifier, node) {
    if (!configValid) return {reason: 'invalid_config'};
    const usage = ts.isExportSpecifier(node) ? node.parent.parent.moduleSpecifier : node.moduleSpecifier;
    const mode = ts.getModeForUsageLocation(module.sf, usage, options);
    const result = ts.resolveModuleName(specifier, module.sf.fileName, options, virtualHost,
      undefined, undefined, mode).resolvedModule;
    if (!result) return {reason: specifier.startsWith('.') ? 'missing_module' : 'external_or_unmapped_module'};
    if (declarationFile(result.resolvedFileName)) return {reason: 'declaration_only_module'};
    const target = modules.get(result.resolvedFileName);
    return target ? {module: target} : {reason: 'excluded_or_uncaptured_module'};
  }
  function resolveExport(module, name, seen = new Set()) {
    if (module.scope.dynamic) return failure('dynamic_scope_unsupported');
    const key = `${module.sf.fileName}#${name}`;
    if (seen.has(key)) return failure('reexport_cycle');
    const entries = module.exports.get(name);
    if (!entries) return failure(module.exports.has('*') ? 'export_star_unsupported' : 'missing_export');
    const next = new Set([...seen, key]);
    const results = entries.map(e => {
      if (e.typeOnly) return failure('type_only_reference');
      if (e.kind === 'definition') {
        if (e.node.name && ts.isIdentifier(e.node.name)) {
          const b = lookup(module.scope, e.node.name.text);
          if (b && (b.writes || b.entries.length !== 1)) return resolveBinding(b, Infinity, next);
        }
        return success(e.definition);
      }
      if (e.kind === 'local') return resolveBinding(lookup(module.scope, e.name), Infinity, next);
      if (e.kind === 'reexport') {
        const target = resolveModule(module, e.specifier, e.node);
        return target.module ? resolveExport(target.module, e.name, next) : failure(target.reason);
      }
      return failure(e.reason);
    });
    if (entries.length !== 1) return failure('ambiguous_export', results.flatMap(r => r.candidates));
    return results[0];
  }
  function resolveBinding(b, position, seen = new Set()) {
    if (!b) return failure('unknown_binding');
    const candidates = b.entries.filter(e => e.definition).map(e => e.definition.id);
    if (b.writes) return failure('reassigned_binding', candidates);
    if (b.entries.length !== 1) return failure('duplicate_binding', candidates);
    const e = b.entries[0];
    if (e.conditional) return failure('conditional_binding', candidates);
    if (e.initialization > position) return failure('before_initialization', candidates);
    if (e.kind === 'definition') return success(e.definition);
    if (e.kind === 'import') {
      if (e.typeOnly) return failure('type_only_reference');
      if (e.namespace) return failure('namespace_requires_known_member');
      const target = resolveModule(e.module, e.specifier, e.node);
      return target.module ? resolveExport(target.module, e.exported, seen) : failure(target.reason);
    }
    return failure(e.reason);
  }
  function reference(node, s, kind, typeOnly = false) {
    let result;
    const name = node.getText();
    let dynamic = s;
    while (dynamic && !dynamic.dynamic) dynamic = dynamic.parent;
    if (dynamic) result = failure('dynamic_scope_unsupported');
    else if (typeOnly) result = failure('type_only_reference');
    else if (ts.isIdentifier(node)) {
      const binding = lookup(s, node.text);
      let enclosing = s;
      const definition = binding?.entries.length === 1 ? binding.entries[0].definition : null;
      while (enclosing && enclosing.owner !== definition?.id) enclosing = enclosing.parent;
      result = resolveBinding(binding, enclosing ? Infinity : node.getStart());
    }
    else if (ts.isPropertyAccessExpression(node) && ts.isIdentifier(node.expression)) {
      const b = lookup(s, node.expression.text);
      if (b && b.entries.length === 1 && !b.writes && b.entries[0].namespace && !b.entries[0].typeOnly) {
        const e = b.entries[0];
        const target = resolveModule(e.module, e.specifier, e.node);
        result = target.module ? resolveExport(target.module, node.name.text) : failure(target.reason);
      } else result = failure(b?.writes ? 'reassigned_binding' : 'method_dispatch_unsupported');
    } else result = failure(ts.isElementAccessExpression(node) ? 'computed_dispatch_unsupported' : 'dynamic_call_unsupported');
    record(kind, s, node, name, result, typeOnly || result.reason === 'type_only_reference');
  }
  function record(kind, s, node, name, result, typeOnly = false) {
    const evidence = site(node);
    if (result.reason) unresolved.push({kind, source: s.owner, scope: s.id, name, reason: result.reason,
      candidates: result.candidates, type_only: typeOnly, site: evidence});
    else relations.push({kind, source: s.owner, scope: s.id, target: result.candidates[0],
      type_only: typeOnly, site: evidence});
  }
  function references(node, s, inType = false) {
    s = nodeScopes.get(node) || s;
    if (ts.isImportDeclaration(node) || ts.isImportEqualsDeclaration(node) || ts.isExportDeclaration(node) ||
        ts.isEnumDeclaration(node) || ts.isModuleDeclaration(node)) return;
    if (ts.isTypeNode(node)) inType = true;
    if (ts.isCallExpression(node) || ts.isNewExpression(node)) {
      reference(node.expression, s, ts.isNewExpression(node) ? 'uses' : 'calls', inType);
      if (ts.isPropertyAccessExpression(node.expression) || ts.isElementAccessExpression(node.expression)) {
        if (!ts.isIdentifier(node.expression.expression)) references(node.expression.expression, s, inType);
        if (ts.isElementAccessExpression(node.expression)) references(node.expression.argumentExpression, s, inType);
      } else if (!ts.isIdentifier(node.expression) && node.expression.kind !== ts.SyntaxKind.ImportKeyword) {
        references(node.expression, s, inType);
      }
      node.typeArguments?.forEach(n => references(n, s, true));
      node.arguments?.forEach(n => references(n, s, inType));
      return;
    }
    if (ts.isPropertyAccessExpression(node) || ts.isElementAccessExpression(node)) {
      reference(node, s, 'uses', inType);
      if (!ts.isIdentifier(node.expression)) references(node.expression, s, inType);
      if (ts.isElementAccessExpression(node)) references(node.argumentExpression, s, inType);
      return;
    }
    if (ts.isIdentifier(node)) {
      const p = node.parent;
      if ((p.name === node && (ts.isDeclarationStatement(p) || ts.isVariableDeclaration(p) ||
          ts.isParameter(p) || ts.isBindingElement(p) || ts.isMethodDeclaration(p) ||
          ts.isFunctionExpression(p) || ts.isPropertyAssignment(p) || ts.isPropertyDeclaration(p) ||
          ts.isJsxAttribute(p) || ts.isTypeParameterDeclaration(p))) ||
          (ts.isBindingElement(p) && p.propertyName === node) ||
          ts.isBreakOrContinueStatement(p) || ts.isLabeledStatement(p) ||
          (ts.isQualifiedName(p) && p.right === node)) return;
      if (inType) {
        if (lookup(s, node.text)) reference(node, s, 'uses', true);
      } else if (lookup(s, node.text)) reference(node, s, 'uses');
      return;
    }
    ts.forEachChild(node, child => references(child, s, inType));
  }
  for (const module of modules.values()) {
    for (const [name, entries] of module.exports) for (const entry of entries) {
      const result = resolveExport(module, name);
      exports.push({path: relative(module.sf.fileName), name, target: result.reason ? null : result.candidates[0],
        candidates: result.candidates, reason: result.reason, type_only: entry.typeOnly, site: site(entry.node)});
      if (entry.kind === 'reexport') record('reexports', module.scope, entry.node,
        `${entry.specifier}#${entry.name}`, result, entry.typeOnly);
      else if (entry.kind === 'unsupported') record('reexports', module.scope, entry.node, name, result, entry.typeOnly);
    }
    for (const node of module.sideEffects) record('imports', module.scope, node,
      node.moduleSpecifier.text, failure('side_effect_import'));
    for (const b of module.scope.bindings.values()) for (const e of b.entries) if (e.kind === 'import') {
      if (e.namespace) {
        unresolved.push({kind: 'imports', source: null, scope: module.scope.id, name: e.specifier,
          reason: e.typeOnly ? 'type_only_reference' : 'namespace_requires_known_member',
          candidates: [], type_only: e.typeOnly, site: site(e.node)});
      } else record('imports', module.scope, e.node, `${e.specifier}#${e.exported}`,
        resolveBinding(b, Infinity), e.typeOnly);
    }
    references(module.sf, module.scope);
  }
  return {schema_version: 1, analyzer_version: '1.0.0', compiler_version: ts.version,
    request_id: request.request_id, offset_unit: 'utf16_code_units', configuration,
    analyzed_files: [...modules.keys()].map(relative).sort(), excluded_files: excluded.sort(order),
    definitions: definitions.sort(order), identity_gaps: identityGaps.sort(order), exports: exports.sort(order), relations: relations.sort(order),
    unresolved: unresolved.sort(order), diagnostics: diagnostics.sort(order)};
}

try {
  const chunks = [];
  let total = 0;
  for (;;) {
    const chunk = Buffer.alloc(65536);
    const length = fs.readSync(0, chunk, 0, chunk.length);
    if (!length) break;
    total += length;
    if (total > 16 * 1024 * 1024) throw new Error('request exceeds 16 MiB');
    chunks.push(chunk.subarray(0, length));
  }
  const bytes = Buffer.concat(chunks);
  const output = JSON.stringify(analyze(JSON.parse(bytes.toString('utf8'))));
  if (Buffer.byteLength(output) > 32 * 1024 * 1024) throw new Error('response exceeds 32 MiB');
  process.stdout.write(output);
} catch (error) {
  process.stderr.write(`CAMI analysis failed: ${error.message}\n`);
  process.exitCode = 1;
}

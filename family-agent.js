/* =========================================================
 * family-agent.js
 * 家族智能管家 - 存储 + 多跳推理 + 人类常识
 * 用法：在 family1.html 中引入本文件
 * ========================================================= */

(function (global) {
  'use strict';

  /* =======================================================
   * 0. 数据容器
   * ======================================================= */
  let familyData = [];       // 原始数组
  let byName = {};           // 人名索引

  /**
   * 初始化数据
   * @param {Array} data - 解析后的 JSONL 数组
   */
  function initData(data) {
    familyData = Array.isArray(data) ? data : [];
    byName = {};
    familyData.forEach(p => {
      if (p && p.n) byName[p.n] = p;
    });
  }

  /**
   * 从文本加载 JSONL
   * @param {string} text
   */
  function loadFromJSONL(text) {
    const lines = text.split(/\r?\n/).filter(l => l.trim());
    const data = [];
    for (const line of lines) {
      try {
        data.push(JSON.parse(line));
      } catch (e) {
        console.warn('解析失败：', line, e);
      }
    }
    initData(data);
    return data.length;
  }

  /* =======================================================
   * 1. 会话记忆（短期）
   * ======================================================= */
  const SessionMemory = {
    history: [],
    lastPerson: null,
    lastResults: [],
    currentPath: [],
    pendingContext: null,

    add(role, text) {
      this.history.push({ role, text, time: Date.now() });
      if (this.history.length > 100) this.history.shift();
    },

    setLastPerson(name, results) {
      this.lastPerson = name;
      this.lastResults = results || [];
    },

    resetPath() {
      this.currentPath = [];
    },

    pushPath(step) {
      this.currentPath.push(step);
    },

    clear() {
      this.history = [];
      this.lastPerson = null;
      this.lastResults = [];
      this.currentPath = [];
      this.pendingContext = null;
    }
  };

  /* =======================================================
   * 2. 长期记忆（持久）
   * ======================================================= */
  const LongTermMemory = {
    key: 'familyAgentMemory',

    load() {
      try {
        return JSON.parse(localStorage.getItem(this.key) || '{}');
      } catch {
        return {};
      }
    },

    save(data) {
      try {
        localStorage.setItem(this.key, JSON.stringify(data));
      } catch (e) {
        console.warn('长期记忆写入失败', e);
      }
    },

    get(field, defaultValue = null) {
      const m = this.load();
      return m[field] ?? defaultValue;
    },

    set(field, value) {
      const m = this.load();
      m[field] = value;
      this.save(m);
    },

    recordQuery(query) {
      const m = this.load();
      m.queryHistory = m.queryHistory || [];
      m.queryHistory.push({ q: query, time: Date.now() });
      if (m.queryHistory.length > 200) m.queryHistory.shift();
      this.save(m);
    },

    setUserIdentity(name) {
      this.set('userIdentity', name);
    },

    getUserIdentity() {
      return this.get('userIdentity');
    }
  };

  /* =======================================================
   * 3. 数据修正存储（持久）
   * ======================================================= */
  const CorrectionStore = {
    key: 'familyCorrections',

    load() {
      try {
        return JSON.parse(localStorage.getItem(this.key) || '[]');
      } catch {
        return [];
      }
    },

    save(list) {
      try {
        localStorage.setItem(this.key, JSON.stringify(list));
      } catch (e) {
        console.warn('修正存储写入失败', e);
      }
    },

    addRelation(nameA, relation, nameB) {
      const list = this.load();
      list.push({
        type: 'relation',
        a: nameA,
        rel: relation,
        b: nameB,
        time: Date.now()
      });
      this.save(list);
    },

    addAlias(alias, realName) {
      const list = this.load();
      list.push({
        type: 'alias',
        alias,
        real: realName,
        time: Date.now()
      });
      this.save(list);
    },

    getSiblings(name) {
      return this.load()
        .filter(x =>
          x.type === 'relation' &&
          x.rel === '兄弟' &&
          (x.a === name || x.b === name)
        )
        .map(x => (x.a === name ? x.b : x.a));
    },

    resolveAlias(name) {
      const hit = this.load().find(x => x.type === 'alias' && x.alias === name);
      return hit ? hit.real : name;
    },

    clear() {
      this.save([]);
    }
  };

  /* =======================================================
   * 4. 基础关系算子
   * ======================================================= */
  function getPerson(name) {
    return byName[name] || null;
  }

  function getFather(name) {
    const p = getPerson(name);
    return p && p.f ? getPerson(p.f) : null;
  }

  function getMother(name) {
    const p = getPerson(name);
    return p && p.m ? getPerson(p.m) : null;
  }

  function getParents(name) {
    const res = [];
    const f = getFather(name);
    const m = getMother(name);
    if (f) res.push(f);
    if (m) res.push(m);
    return res;
  }

  function getSpouses(name) {
    const p = getPerson(name);
    if (!p || !p.sp) return [];
    const arr = Array.isArray(p.sp) ? p.sp : [p.sp];
    return arr.map(x => getPerson(x)).filter(Boolean);
  }

  function getChildren(name) {
    return familyData.filter(x => x.f === name || x.m === name);
  }

  function getSons(name) {
    return getChildren(name).filter(x => x.s === '男');
  }

  function getDaughters(name) {
    return getChildren(name).filter(x => x.s === '女');
  }

  function getSiblings(name) {
    const p = getPerson(name);
    if (!p) return [];
    const set = new Map();
    familyData.forEach(x => {
      if (x.n === name) return;
      if ((p.f && x.f === p.f) || (p.m && x.m === p.m)) {
        set.set(x.n, x);
      }
    });
    // 加入人工补充的兄弟
    CorrectionStore.getSiblings(name).forEach(n => {
      const person = getPerson(n);
      if (person) set.set(person.n, person);
    });
    return Array.from(set.values());
  }

  function getBrothers(name) {
    return getSiblings(name).filter(x => x.s === '男');
  }

  function getSisters(name) {
    return getSiblings(name).filter(x => x.s === '女');
  }

  /* =======================================================
   * 5. 关系算子表
   * ======================================================= */
  const relationOps = {
    '妈': getMother,
    '母亲': getMother,
    '娘': getMother,
    '妈妈': getMother,

    '爸': getFather,
    '父亲': getFather,
    '爹': getFather,
    '爸爸': getFather,

    '父母': getParents,
    '爸妈': getParents,
    '双亲': getParents,

    '配偶': getSpouses,
    '妻': getSpouses,
    '夫': getSpouses,
    '老婆': getSpouses,
    '老公': getSpouses,

    '儿子': getSons,
    '闺女': getDaughters,
    '女儿': getDaughters,
    '孩子': getChildren,
    '子女': getChildren,

    '兄弟': getBrothers,
    '哥哥': getBrothers,
    '弟弟': getBrothers,
    '姐妹': getSisters,
    '姐姐': getSisters,
    '妹妹': getSisters,
    '兄弟姐妹': getSiblings
  };

  /* =======================================================
   * 6. 人类常识：辈分与模糊问法
   * ======================================================= */
  const CommonSense = {
    /**
     * 上一辈：父母 + 父母的兄弟姐妹（广义）
     */
    getElders(name, broad = true) {
      const parents = getParents(name);
      const list = [...parents];
      if (broad) {
        parents.forEach(p => {
          getSiblings(p.n).forEach(s => {
            if (!list.find(x => x.n === s.n)) list.push(s);
          });
        });
      }
      return list;
    },

    /**
     * 模糊问法归一化
     */
    normalize(query) {
      return query
        .replace(/上一辈|长辈|上辈|老辈子|上面的人/g, '上一辈')
        .replace(/爸妈|爹娘|二老/g, '父母')
        .replace(/家里人|家人/g, '父母及兄弟姐妹');
    },

    /**
     * 是否属于“上一辈”问法
     */
    isElderQuery(query) {
      return /上一辈|长辈|上辈|老辈子|上面的人/.test(query);
    }
  };

  /* =======================================================
   * 7. 关系路径解析
   * ======================================================= */
  function parseRelationPath(query) {
    const relWords = Object.keys(relationOps).sort((a, b) => b.length - a.length);
    const names = Object.keys(byName).sort((a, b) => b.length - a.length);

    let rest = query.trim();
    let start = null;

    // 找起点：优先匹配最长人名
    for (const n of names) {
      if (rest.startsWith(n)) {
        start = n;
        rest = rest.slice(n.length);
        break;
      }
    }

    // 允许“的”作为分隔符
    rest = rest.replace(/^的/, '');

    if (!start) {
      // 尝试从任意位置提取人名
      for (const n of names) {
        const idx = rest.indexOf(n);
        if (idx >= 0) {
          start = n;
          rest = rest.slice(idx + n.length);
          break;
        }
      }
    }

    if (!start) return { error: '未识别起点人物' };

    const tokens = [start];

    // 逐词切分关系
    while (rest.length) {
      rest = rest.replace(/^的/, '');
      let matched = false;
      for (const w of relWords) {
        if (rest.startsWith(w)) {
          tokens.push(w);
          rest = rest.slice(w.length);
          matched = true;
          break;
        }
      }
      if (!matched) {
        // 遇到不认识的词，跳过“的”再试
        if (rest[0] === '的') {
          rest = rest.slice(1);
          continue;
        }
        break;
      }
    }

    return { tokens };
  }

  /* =======================================================
   * 8. 多跳推理执行
   * ======================================================= */
  function executeRelationPath(query) {
    // 常识问法优先
    if (CommonSense.isElderQuery(query)) {
      const parsed = parseRelationPath(query);
      if (parsed.error) return { error: parsed.error };
      const name = parsed.tokens[0];
      const elders = CommonSense.getElders(name, true);
      return {
        start: name,
        path: `起点：${name}\n上一辈（广义）`,
        result: elders.map(x => `${x.n}（${x.s}，${x.info || '无补充'}）`),
        context: { start: name, current: elders, path: [] }
      };
    }

    const parsed = parseRelationPath(query);
    if (parsed.error) return { error: parsed.error };

    const { tokens } = parsed;
    const ctx = {
      start: tokens[0],
      current: [getPerson(tokens[0])].filter(Boolean),
      path: [`起点：${tokens[0]}`],
      failedAt: null
    };

    if (!ctx.current.length) {
      return { error: `未找到人物「${tokens[0]}」` };
    }

    for (let i = 1; i < tokens.length; i++) {
      const rel = tokens[i];
      const fn = relationOps[rel];
      if (!fn) {
        return {
          path: ctx.path.join('\n') + `\n${rel}：❌ 无法识别`,
          error: `无法识别关系词「${rel}」`,
          context: ctx
        };
      }

      let next = [];
      ctx.current.forEach(p => {
        const r = fn(p.n);
        if (Array.isArray(r)) next.push(...r);
        else if (r) next.push(r);
      });

      // 去重
      next = next.filter((v, idx, arr) => arr.findIndex(x => x.n === v.n) === idx);

      if (!next.length) {
        ctx.failedAt = rel;
        return {
          path: ctx.path.join('\n') + `\n${rel}：❌ 无结果`,
          error: `在第 ${i} 跳「${rel}」处查不到记录。`,
          context: ctx
        };
      }

      ctx.path.push(`${rel}：${next.map(x => x.n).join('、')}`);
      ctx.current = next;
    }

    return {
      start: ctx.start,
      path: ctx.path.join('\n'),
      result: ctx.current.map(x => `${x.n}（${x.s}，${x.info || '无补充'}）`),
      context: ctx
    };
  }

  /* =======================================================
   * 9. 主入口：ask
   * ======================================================= */
  function ask(query) {
    if (!query || !query.trim()) return { error: '请输入问题' };

    // 记录问法
    LongTermMemory.recordQuery(query);

    // 别名纠正
    query = query.replace(/[\u4e00-\u9fa5]+/g, w => CorrectionStore.resolveAlias(w));

    // 指代消解
    if (/他们|她们|这些人|那些人/.test(query) && SessionMemory.lastResults.length) {
      const names = SessionMemory.lastResults.map(x => x.n || x).join('、');
      query = query.replace(/他们|她们|这些人|那些人/, names);
    }

    // 常识归一化
    query = CommonSense.normalize(query);

    // 执行推理
    const result = executeRelationPath(query);

    // 写入会话记忆
    SessionMemory.add('user', query);
    if (result && result.result) {
      SessionMemory.add('agent', result.result.join('；'));
      SessionMemory.setLastPerson(result.start, result.result);
    } else {
      SessionMemory.add('agent', String(result.error || result));
    }

    return result;
  }

  /* =======================================================
   * 10. 对外暴露
   * ======================================================= */
  const FamilyAgent = {
    initData,
    loadFromJSONL,
    ask,
    executeRelationPath,
    parseRelationPath,
    SessionMemory,
    LongTermMemory,
    CorrectionStore,
    CommonSense,
    getPerson,
    getParents,
    getFather,
    getMother,
    getSiblings,
    getChildren,
    getSpouses,

    /**
     * 便捷：添加修正关系
     */
    addRelation(a, rel, b) {
      CorrectionStore.addRelation(a, rel, b);
    },

    /**
     * 便捷：添加别名
     */
    addAlias(alias, real) {
      CorrectionStore.addAlias(alias, real);
    }
  };

  global.FamilyAgent = FamilyAgent;

})(typeof window !== 'undefined' ? window : globalThis);

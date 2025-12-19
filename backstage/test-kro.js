#!/usr/bin/env node

/**
 * Simple Kro test runner and vaor
 * Usage: node test-kro.js [test-name]p]
 */

const { execSync } = require('child_process');
const { existsSync } = requir');
);

const testSuites = {
  'integration': {
    name: 'Plugin Integration',
    pattern: 'kro-plugin-integration.test.ts',
    description: 'Tests for Kro plugiation'
  },
  {
ration', 
    pattern: 'kro-catalog-integ.ts',
    description: 'Tests for ResourceGroup catalog integ'
  },

    nams',
    pattern: 'kro-resource-group-workflows.test.ts', 
    description: 'Tests for ResourceGroupgement'
,
  'permissions': {
    name: 'Permissions 
    pattern: 'kro-per
    description: 'Tests for RBAC an
  },

    name: 'Security Components',
    pattern: 'kro-s
    description: 'Tests for security, audit logging,
  },
  'end': {
 tion',
t.tsx',
    description: 'Tes
  }
};

function showHelp() {
  console.log('🧪 Kro Plugin Test Runner');
  console.log('═'.repeat(50));
  conge:');
  console.log('  nsts');
  console.log('  node test-
  console.log('  node test-kro.js --help             # Show this help');
  console.log('');
  console.log('Available test suites:');
  {
);
  });
  console.log('');
;
  console.log('  node test-kro.js integration        # sts');
  console.log('
  console.l;
}

function validateTestFiles
  console.log('🔍 Valida
  console.log('═'.repeat(40));
  
  let allValid = true;
  
 files
  const backendTeststs__';
  const backendTests = [
    'kro-pluest.ts',
    'kro-catalog-integration.test.ts', 
    'kro-resource-grouest.ts',
    'kro-permissi.ts',
    'kro-security.test.ts'
  ];
  
 

    con
}
  main();== module) {ain =require.m;
}

if (workflows')terface User in('   ✓ le.log  conson');
 integratio componentnd Frontelog('   ✓
  console. logging');uditdling and a ✓ Error han  ole.log(');
  considation'mission val pernd'   ✓ RBAC ag(console.long');
   trackiatus and sttionshipsy rela  ✓ Entit' g(  console.losing');
proces entity egration andog int Catal'   ✓ole.log(t');
  consd managemention anceGroup creaour('   ✓ Resle.log consory');
 n discoveitiofinurceGraphDeeso.log('   ✓ Rconsolevity'); 
  ecticonns cluster rnete('   ✓ Kubee.logsol);
  configuration'nd conialization a Plugin initg('   ✓nsole.lo coary:');
 erage Summt Coves('\n📊 Tle.logso
  con');completed!s plugin test\n🎉 Kro ('sole.logcon
  
  }
  1);.exit(cess   pro{
 uccess) 
  if (!s;
  (suiteKey)unTestssuccess = rt 
  cons[0];teKey = argsonst sui tests
  c 
  // Run
 );y!\n'lled successfues validatt fil All tesog('\n✅ole.l  
  cons  }
it(1);
.exss;
    procereated.')e ciles arll f ase ensureissing. Pleales are mome test fi.log('\n❌ S   console) {
 s()stFileateTe if (!validirst
 test files f Validate   //
  n;
  }

    returowHelp();
    shes('-h')) { args.includlp') ||des('--he(args.inclu;
  
  if e(2)argv.slicocess. args = prnst
  coon main() {

functi}
}  false;
   return message);
 r.or:', errog('Err  console.lo!');
  ailedTests f'\n❌ .log(  consoleor) {
  atch (err c 
  }  
 eturn true; r
   ully!');ted successfests comple'\n✅ Tsole.log(
    con});
    ut: 120000 t', timeoheristdio: 'in(command, { ync  execS
  and}\n`);g: ${comminecut(`🔄 Exogconsole.l     }
    
:kro';
   stte= 'yarn mmand      cots\n');
 o tesKrRunning all log('📋 onsole. ce {
     
    } elsrn false;etu);
      r ')s).join(',itetestSuObject.keys(es:', ailable suit.log('Av     consoleeKey}`);
 uituite: ${sest swn tno(`❌ Unknsole.log    coteKey) {
  ui} else if (s    erage`;
ose --no-cov-verbattern}" -"${suite.pern=hPattstPatrn test --te= `yamand 
      com  \n`);
    escription}{suite.d📝 $sole.log(`;
      conme}`)te.na{suiing: $g(`📋 Runn console.lo  y];
   es[suiteKeSuituite = test    const sey]) {
  uiteKes[stestSuity && teKe  if (sui
    
   command; {
    let try40));
  
 '.repeat(g('═onsole.los');
  cstugin Tenning Kro Pl('🚀 Ruonsole.logll) {
  cuiteKey = nunTests(sction ru

fun;
}n allValid
  
  retur;    }
  })alse;
lid = f     allVa
 OT FOUND`);le} - N`❌ ${finsole.log(  colse {
      } efile}`);
  e.log(`✅ ${    console)) {
  (fil(existsSyncf  ile => {
   orEach(files.f supportFies:');
 port Fil'\n🛠️  Supe.log(  consol ];
  

 s'processor.tource-group-es/kro-rcessorsrons/catalog-pc/plugisrs/backend/ge 'packa
   e.ts',group-servicrce-/kro-resou/pluginsackend/src/bpackages    'nfig.js',
__/jest.co/__tests/src/pluginsages/backendckpa,
    'p.ts'ests__/setu_ts/_ginsrc/pluckend/'packages/ba= [
    Files rtt suppo
  consesilport f Check sup
  //});
  
    }
   false;lValid =  al
    D`);T FOUN${test} - NOle.log(`❌ conso
          } else {;
t}`) ${tesole.log(`✅   consath)) {
   Sync(pf (exists
    i test);stDir,rontendTein(fh = jopatnst  co
    {st =>Each(tes.forndTest
  frontets:');nd Tesnte\n🎨 Fro('ogsole.l
  con  .tsx'];
estn.tgrationte['KroI = stsendTeontst frs__';
  cons/__testrc/component/sappages/r = 'packDiestt frontendTconst files
  d tesntenroheck f // C 
 
 );  }
  }
   false; allValid =);
      NOT FOUND``❌ ${test} -sole.log(con    lse {
  } e
    }`);g(`✅ ${testle.lo     consoh)) {
 ync(patexistsS  if (st);
  TestDir, te(backendpath = joinst 
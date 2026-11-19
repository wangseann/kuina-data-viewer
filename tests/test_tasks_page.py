from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parent.parent


class TaskPageTests(unittest.TestCase):
    def test_legacy_board_routes_new_work_to_unique_batches_and_prepares_original_assignments(self):
        script = r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const copied=[];
const document={createElement(tag){return {tag,childNodes:[],listeners:{},append(...nodes){this.childNodes.push(...nodes)},addEventListener(name,fn){this.listeners[name]=fn}}}};
const source=fs.readFileSync('docs/tasks.js','utf8').split('async function refresh()')[0];
const context={KuinaTasks:{requestURL(){throw Error('Legacy board must not create new claims')}},document,navigator:{clipboard:{async writeText(text){copied.push(text)}}}};
vm.createContext(context);vm.runInContext(source,context);
const available=context.renderActions({id:'old-1',status:'available'},'seann',true);
assert.equal(available.childNodes[0].href,'unique.html');
const assigned=context.renderActions({id:'old-1',status:'assigned',assignee:'seann',assignment_issue:5},'seann',true);
const button=assigned.childNodes.find(n=>n.tag==='button');assert(button);
button.listeners.click();
assert(copied[0].includes('prepare-work old-1 --person seann --assignment-issue 5'));
assert(!assigned.childNodes.some(n=>n.textContent==='Release via GitHub'));
'''
        result = subprocess.run(['node', '-e', script], cwd=ROOT, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr.decode())

    def test_new_batch_notice_keeps_legacy_assignment_and_report_controls(self):
        from html.parser import HTMLParser
        class Elements(HTMLParser):
            def __init__(self):super().__init__();self.ids=set();self.links=[]
            def handle_starttag(self,tag,attrs):
                attrs=dict(attrs)
                if 'id'in attrs:self.ids.add(attrs['id'])
                if tag=='a':self.links.append(attrs.get('href'))
        page=(ROOT/'docs/tasks.html').read_text();elements=Elements();elements.feed(page)
        self.assertIn('unique.html',elements.links)
        self.assertIn('For new repair batches',page)
        self.assertIn('existing assignments and reports',page)
        self.assertTrue({'identity','my-work','available-work','task-list','poll-command','request-note','refresh'}<=elements.ids)
        self.assertIn('read-batch TASK_ID',page)
        self.assertIn('Report work and provenance',page)

    def test_public_snapshot_contract(self):
        subprocess.run(['node', str(ROOT / 'tests/test_tasks_core.js')], check=True, capture_output=True)

    def test_board_cannot_claim_from_a_static_browser(self):
        page = (ROOT / 'docs/tasks.html').read_text()
        source = (ROOT / 'docs/tasks.js').read_text()
        self.assertIn("connect-src 'self'", page)
        self.assertIn('authoritative', page)
        for forbidden in ['localStorage', 'innerHTML', 'eval(', '/datashare/', 'method:']:
            self.assertNotIn(forbidden, source)
        self.assertIn('tasks-summary.json', source)


if __name__ == '__main__':
    unittest.main()

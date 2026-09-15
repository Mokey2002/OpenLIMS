const { test, expect } = require('@playwright/test');
test('sequence workbench loads, edits, undoes, and protects unsaved work', async ({ page }) => {
  const sequence = { id: 1, name: 'Test construct', sequence: 'ACGTACGTACGT', sequence_type: 'DNA', topology: 'LINEAR', project: 1, annotations: [{name:'Gene A',start:0,end:4,direction:1,color:'#22c55e'}], primers:[],translations:[],highlights:[],enzymes:[],revisions:[] };
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname;
    let body = [];
    if(path.endsWith('/me/')) body={id:1,username:'editor',roles:['admin']};
    else if(path.endsWith('/ui-settings/')) body={ui_language:'en'};
    else if(path.endsWith('/sequences/1/workspace/')) body=sequence;
    else if(path.endsWith('/sequences/')) body=[sequence];
    else if(path.endsWith('/projects/')) body=[{id:1,name:'Project A',code:'A'}];
    await route.fulfill({json:body});
  });
  await page.goto('/sequences');
  await page.getByRole('combobox',{name:'Load saved workspace'}).selectOption('1');
  await expect(page.getByRole('toolbar',{name:'Sequence tools'})).toBeVisible();
  await page.getByRole('button',{name:'Feature editor',exact:true}).click();
  await page.getByRole('button',{name:'Gene A',exact:true}).click();
  await page.getByLabel('Name',{exact:true}).fill('Gene B');
  await page.getByRole('button',{name:'Apply changes',exact:true}).click();
  await expect(page.getByText('Unsaved changes',{exact:true})).toBeVisible();
  await page.getByRole('button',{name:'Undo',exact:true}).click();
  await expect(page.getByText('No unsaved changes',{exact:true})).toBeVisible();
  await page.getByRole('button',{name:'Redo',exact:true}).click();
  page.once('dialog', dialog => dialog.dismiss());
  await page.getByRole('button',{name:'New sequence',exact:true}).click();
  await expect(page.getByText('Unsaved changes',{exact:true})).toBeVisible();
});

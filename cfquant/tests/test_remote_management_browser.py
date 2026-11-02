"""Local remote-management form, without contacting the public site."""
from cfquant.tests.test_tutorial_reader import browser, page, expect, frontend_url, open_app


def test_opt_in_form_requires_website_key_and_keeps_it_out_of_storage(page,frontend_url):
    _,errors=open_app(page,frontend_url,setup_required=False)
    posted=[]
    data={'enabled':False,'configured':False,'state':'disabled','permissions':{}}
    def respond(route):
        if route.request.method=='POST':
            body=route.request.post_data_json;posted.append(body)
            data.update(enabled=body['enabled'],configured=True,name='Local deployment',instance_id='fixture',key_prefix='cfqr_fixture',state='connecting',permissions=body.get('permissions',{}))
        route.fulfill(json={'ok':True,'data':data})
    page.route('**/api/remote-management',respond)
    page.evaluate("() => { hideOnboardingModal({force:true}); setView('settings');setSettingsTab('remote-management'); }")
    page.locator('#remoteRefresh').click()
    form=page.locator('#remoteConnectionForm')
    expect(form.locator('[name=enabled]')).not_to_be_checked()
    form.locator('[name=enabled]').check()
    expect(form.locator('[name=account], [name=password], [name=name]')).to_have_count(0)
    form.locator('[type=submit]').click()
    expect(page.locator('#remoteConnectionMessage')).to_contain_text('请先在官网创建部署')
    assert not posted
    form.locator('[name=api_key]').fill('cfqr_synthetic-project-key')
    form.locator('[name=queries]').check()
    form.locator('[type=submit]').click()
    expect(page.locator('#remoteConnectionMessage')).to_contain_text('已保存')
    expect(form.locator('[name=api_key]')).to_have_value('')
    expect(page.locator('#remoteProjectInfo')).to_contain_text('Local deployment')
    assert posted[0]['api_key']=='cfqr_synthetic-project-key'
    assert not {'account','password','name','note'} & posted[0].keys()
    assert posted[0]['permissions']=={'queries':True,'service_control':False,'qmt_control':False}
    assert 'cfqr_synthetic-project-key' not in page.evaluate('JSON.stringify(state)+JSON.stringify(localStorage)+JSON.stringify(sessionStorage)')
    form.locator('[type=submit]').click()
    expect(page.locator('#remoteConnectionMessage')).to_contain_text('已保存')
    assert posted[-1]['api_key']==''
    form.locator('[name=enabled]').uncheck();form.locator('[type=submit]').click()
    expect(page.locator('#remoteConnectionMessage')).to_contain_text('已关闭')
    assert posted[-1]=={'enabled':False,'permissions':{}}
    assert errors==[]

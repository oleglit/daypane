# -*- coding: utf-8 -*-
"""三页轮播的插件侧回归：分页缓存、图源 URL、手势与抢占。"""
import unittest

import kindle_plugin_test as harness

lua = harness.lua


class PageTests(unittest.TestCase):
    def test_pages_caches_endpoints_and_gestures(self):
        lua.execute('''
        local d = Plugin:new{language='ru', auto_on=false}
        d.cacheDir = function() return '/tmp' end
        d.host = 'pc:8787'
        d.cloud = 'https://example.test/screen.png'
        d.dash_widget = {}
        d._shown_pages = {}
        d._refreshes = 0
        d._opts = {}
        d.fileExists = function() return false end
        d.record = function() end
        d.option = function(self, key, default) return default end
        d.setOption = function(self, k, v) self._opts[k] = v end
        d.requestRefresh = function(self)
            self._refreshes = self._refreshes + 1
            return true
        end
        d.showDashboard = function(self, path)
            self._shown_pages[#self._shown_pages + 1] = path
            return true
        end

        -- 页码钳制：升级后设置里的脏值不能拼出孤儿缓存文件。
        assert(d:currentPage() == 1)
        d.page = 99; assert(d:currentPage() == 1)
        d.page = -3; assert(d:currentPage() == 1)
        d.page = '2'; assert(d:currentPage() == 2)

        -- 慢信息/闲读页按 2 小时刷新，页 1 仍是 30 分钟。
        d.page = 1; assert(d:intervalSec() == 1800)
        d.page = 2; assert(d:intervalSec() == 7200)
        d.page = 3; assert(d:intervalSec() == 7200)

        -- 每页 / 每种语言各一份缓存，页 1 沿用旧文件名。
        d.page = 1; local p1 = d:cacheImg()
        d.page = 2; local p2 = d:cacheImg()
        d.page = 3; local p3 = d:cacheImg()
        assert(p1 ~= p2 and p2 ~= p3 and p1 ~= p3)
        assert(p2:match('_p2%.png$') and p3:match('_p3%.png$'))
        assert(d:cacheTs():match('_p3'))
        d.language = 'en'
        assert(d:cacheImg():match('_en_p3%.png$'))
        assert(d:cacheTs():match('_en_p3'))
        d.language = 'zh'

        -- 局域网 URL 带页码；云端 Pages 只有页 1，页 2/3 不能挂云图源。
        d.page = 1
        local e1 = d:endpoints()
        assert(#e1 == 2 and e1[1].url:match('/api/screen%?lang=ru&page=1$'))
        d.page = 2
        local e2 = d:endpoints()
        assert(#e2 == 1 and e2[1].url:match('page=2$'))
        assert(d:manifestUrl(e2[1].url):match('/api/display%?lang=ru&page=2$'))
        d.page = 3
        assert(#d:endpoints() == 1)

        -- 手势：左滑下一页、右滑上一页，首尾相接。
        d.page = 1
        local c = d:buildScreen('/tmp/never.png', 1072, 1448)
        local zones = c._test_touch_zones
        assert(zones and #zones == 2, 'full-screen tap and swipe zones must be registered')
        assert(zones[1].id == 'daypane_tap' and zones[2].id == 'daypane_swipe')
        assert(zones[1].screen_zone.ratio_w == 1 and zones[2].screen_zone.ratio_h == 1)
        zones[2].handler({direction='west', pos={x=500,y=700}})
        assert(d:currentPage() == 2 and d._opts.page == 2)
        zones[2].handler({direction='east', pos={x=500,y=700}})
        assert(d:currentPage() == 1)
        zones[2].handler({direction='east', pos={x=500,y=700}})
        assert(d:currentPage() == 3, 'wrapping backwards from page 1')
        zones[2].handler({direction='west', pos={x=500,y=700}})
        assert(d:currentPage() == 1, 'wrapping forwards from page 3')

        -- 点按两侧换页，中间 56% 不响应。
        zones[1].handler({pos={x=1000,y=700}})
        assert(d:currentPage() == 2)
        zones[1].handler({pos={x=100,y=700}})
        assert(d:currentPage() == 1)
        zones[1].handler({pos={x=536,y=700}})
        assert(d:currentPage() == 1, 'centre taps must not flip pages')

        -- 切页作废进行中的刷新，并重新发起一次（旧页的图不能盖到新页）。
        local seen = d._refreshes
        d._busy = true
        assert(d:gotoPage(2) == true)
        assert(d._busy == false and d._refreshes == seen + 1)
        assert(d:gotoPage(2) == false and d._refreshes == seen + 1, 'same page is a no-op')

        -- 顶部点按 / 下滑仍然是退出，且退出优先于翻页。
        d.page = 1
        zones[1].handler({pos={x=1000,y=50}})
        assert(d.dash_widget == nil, 'top tap must exit, not change page')
        d.dash_widget = {}
        zones[2].handler({direction='south', pos={x=100,y=100}})
        assert(d.dash_widget == nil, 'top swipe down must exit')
        print('PASS: page clamping, per-page caches, page-aware URLs, swipe/tap gestures, preemption, exit')
        ''')


if __name__ == '__main__':
    unittest.main()

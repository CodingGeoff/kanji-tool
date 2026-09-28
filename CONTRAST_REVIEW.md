# 译文最小对立 · 人工抽检表

由 `python contrast_sample.py --md CONTRAST_REVIEW.md` 生成。

机器已自动核验：四项互不相同、答案未被改写、2×2 每轴 2:2、除审计申报外不引入新实词、改写结果不是病句。

**人工只需判断一件事**：标 ✘ 的三项里，有没有哪一条其实也能当这句日文的合法译文？（若有，请记下题号，那说明对应那条轴的日文侧证据规则需要收紧。）

本表共 99 题，按语法轴分层抽样。


## 轴：comparative+polarity（3 题）

**1. 日文**：与えられるより与える方がいっそう恵まれている。　`matrix_2x2`

- ✘ 施比受更没有福。　<sub>肯否：有 → 没有</sub>
- ✔ 施比受更有福。
- ✘ 受比施更有福。　<sub>比较方向：施 ↔ 受 互换</sub>
- ✘ 受比施更没有福。　<sub>比较方向：施 ↔ 受 互换；肯否：有 → 没有</sub>
- 依据：日文用「〜より」显式标出了比较的基准，互换两侧后意思相反；日文句里没有任何否定形态素（ない／ぬ／ません），说的是肯定的事

**2. 日文**：猫は犬より小さい。　`matrix_2x2`

- ✘ Cats are not smaller than dogs.　<sub>肯否：are → are not</sub>
- ✔ Cats are smaller than dogs.
- ✘ Dogs are not smaller than Cats.　<sub>比较方向：Cats ↔ dogs 互换；肯否：are → are not</sub>
- ✘ Dogs are smaller than Cats.　<sub>比较方向：Cats ↔ dogs 互换</sub>
- 依据：日文用「〜より」显式标出了比较的基准，互换两侧后意思相反；日文句里没有任何否定形态素（ない／ぬ／ません），句尾谓语是肯定的

**3. 日文**：女性は男性よりも低い給料で雇われている。　`matrix_2x2`

- ✔ Women are employed at a lower salary than men.
- ✘ Women are not employed at a lower salary than men.　<sub>肯否：are → are not</sub>
- ✘ Men are not employed at a lower salary than Women.　<sub>比较方向：Women ↔ men 互换；肯否：are → are not</sub>
- ✘ Men are employed at a lower salary than Women.　<sub>比较方向：Women ↔ men 互换</sub>
- 依据：日文用「〜より」显式标出了比较的基准，互换两侧后意思相反；日文句里没有任何否定形态素（ない／ぬ／ません），句尾谓语是肯定的

## 轴：conj+modal（3 题）

**4. 日文**：恐い話が聞きたいなら、数週間前に私が見た夢のことを話してあげるよ。　`matrix_2x2`

- ✘ 即使你必須聽恐怖故事，那我就把幾個星期前作的夢告訴你吧。　<sub>分句逻辑：如果 → 即使；情态：想 → 必須</sub>
- ✘ 如果你必須聽恐怖故事，那我就把幾個星期前作的夢告訴你吧。　<sub>情态：想 → 必須</sub>
- ✔ 如果你想聽恐怖故事，那我就把幾個星期前作的夢告訴你吧。
- ✘ 即使你想聽恐怖故事，那我就把幾個星期前作的夢告訴你吧。　<sub>分句逻辑：如果 → 即使</sub>
- 依据：日文里有条件形「〜たら／〜ば／〜なら」；日文里有愿望形「〜たい」

**5. 日文**：この本を読み終わらなければならないので出かけない。　`matrix_2x2`

- ✘ I am not going out although I may finish reading this book.　<sub>分句逻辑：because → although；情态：have to → may</sub>
- ✔ I am not going out because I have to finish reading this book.
- ✘ I am not going out because I may finish reading this book.　<sub>情态：have to → may</sub>
- ✘ I am not going out although I have to finish reading this book.　<sub>分句逻辑：because → although</sub>
- 依据：日文里有表示原因的「から／ので」，没有逆接的「のに／けど」；日文里有义务表达「〜なければならない／〜ないといけない」

**6. 日文**：私たちは勉強したいので学校へ行きます。　`matrix_2x2`

- ✘ We go to school although we want to learn.　<sub>分句逻辑：because → although</sub>
- ✔ We go to school because we want to learn.
- ✘ We go to school because we have to learn.　<sub>情态：want to → have to</sub>
- ✘ We go to school although we have to learn.　<sub>分句逻辑：because → although；情态：want to → have to</sub>
- 依据：日文里有表示原因的「から／ので」，没有逆接的「のに／けど」；日文里有愿望形「〜たい」

## 轴：conj+person（3 题）

**7. 日文**：「終電逃したらどうしよう」「帰れなかったらうち泊めてやるよ」　`matrix_2x2`

- ✘ "What should I do even if I miss the last train?" "If you aren't able to get back home then you can stay here."　<sub>分句逻辑：if → even if</sub>
- ✘ "What should he does if he misses the last train?" "If you aren't able to get back home then you can stay here."　<sub>人称：I → he</sub>
- ✘ "What should he does even if he misses the last train?" "If you aren't able to get back home then you can stay here."　<sub>分句逻辑：if → even if；人称：I → he</sub>
- ✔ "What should I do if I miss the last train?" "If you aren't able to get back home then you can stay here."
- 依据：日文里有条件形「〜たら／〜ば／〜なら」；日文里显式出现了代词（私／僕），人称不是靠上下文猜的

**8. 日文**：七夕は漫画によく出てくるので、私もそこそこ知っています。　`matrix_2x2`

- ✘ 七夕在漫畫裡常常出現但是你也了解它的意思。　<sub>分句逻辑：所以 → 但是；人称：我 → 你</sub>
- ✘ 七夕在漫畫裡常常出現但是我也了解它的意思。　<sub>分句逻辑：所以 → 但是</sub>
- ✔ 七夕在漫畫裡常常出現所以我也了解它的意思。
- ✘ 七夕在漫畫裡常常出現所以你也了解它的意思。　<sub>人称：我 → 你</sub>
- 依据：日文里有表示原因的「から／ので」，没有逆接的「のに／けど」；日文里显式出现了代词（私／僕）

**9. 日文**：妻が電話してきたら、私は重要な会議中で出られないと言ってください。　`matrix_2x2`

- ✘ If your wife calls, just tell her you're in an important meeting and cannot be disturbed.　<sub>人称：my → your</sub>
- ✘ Even if my wife calls, just tell her I'm in an important meeting and cannot be disturbed.　<sub>分句逻辑：If → even if</sub>
- ✔ If my wife calls, just tell her I'm in an important meeting and cannot be disturbed.
- ✘ Even if your wife calls, just tell her you're in an important meeting and cannot be disturbed.　<sub>分句逻辑：If → even if；人称：my → your</sub>
- 依据：日文里有条件形「〜たら／〜ば／〜なら」；日文里显式出现了代词（私／僕），人称不是靠上下文猜的

## 轴：conj+time（3 题）

**10. 日文**：明日、天気がよければピクニックに行くつもりです。　`matrix_2x2`

- ✘ 如果昨天天气好，那么我们就去野餐。　<sub>时间：明天 → 昨天</sub>
- ✘ 即使明天天气好，那么我们就去野餐。　<sub>分句逻辑：如果 → 即使</sub>
- ✘ 即使昨天天气好，那么我们就去野餐。　<sub>分句逻辑：如果 → 即使；时间：明天 → 昨天</sub>
- ✔ 如果明天天气好，那么我们就去野餐。
- 依据：日文里有条件形「〜たら／〜ば／〜なら」；日文里出现時間名詞「明日」，时间点是显式的

**11. 日文**：夜中に雨が降ったので道がたいへん悪かった。　`matrix_2x2`

- ✘ The roads were very muddy although it had rained during the morning.　<sub>分句逻辑：since → although；时间：night → morning</sub>
- ✘ The roads were very muddy although it had rained during the night.　<sub>分句逻辑：since → although</sub>
- ✔ The roads were very muddy since it had rained during the night.
- ✘ The roads were very muddy since it had rained during the morning.　<sub>时间：night → morning</sub>
- 依据：日文里有表示原因的「から／ので」，没有逆接的「のに／けど」；日文里出现時間名詞「夜」，时间点是显式的

**12. 日文**：明日天気なら外出します。　`matrix_2x2`

- ✔ I will go out if it is fine tomorrow.
- ✘ I will go out if it is fine today.　<sub>时间：tomorrow → today</sub>
- ✘ I will go out even if it is fine today.　<sub>分句逻辑：if → even if；时间：tomorrow → today</sub>
- ✘ I will go out even if it is fine tomorrow.　<sub>分句逻辑：if → even if</sub>
- 依据：日文里有条件形「〜たら／〜ば／〜なら」；日文里出现時間名詞「明日」，时间点是显式的

## 轴：modal（3 题）

**13. 日文**：私たちは、パーティーを開くための部屋を借りねばならない。　`four_way_slot`

- ✘ We want to hire a room to hold the party in.　<sub>情态：have to → want to</sub>
- ✔ We have to hire a room to hold the party in.
- ✘ We may hire a room to hold the party in.　<sub>情态：have to → may</sub>
- ✘ We should hire a room to hold the party in.　<sub>情态：have to → should</sub>
- 依据：日文里有义务表达「〜なければならない／〜ないといけない」

**14. 日文**：理論には実践が伴わなければならない。　`four_way_slot`

- ✘ 理論應該與實踐相隨。　<sub>情态：必須 → 應該</sub>
- ✔ 理論必須與實踐相隨。
- ✘ 理論想與實踐相隨。　<sub>情态：必須 → 想</sub>
- ✘ 理論可以與實踐相隨。　<sub>情态：必須 → 可以</sub>
- 依据：日文里有义务表达「〜なければならない／〜ないといけない」

**15. 日文**：そして、入国審査官の審査を受けて上陸許可を受けなければなりません。　`four_way_slot`

- ✘ They should then go through a landing examination conducted by inspection officers before they can obtain landing permission.　<sub>情态：must → should</sub>
- ✘ They may then go through a landing examination conducted by inspection officers before they can obtain landing permission.　<sub>情态：must → may</sub>
- ✔ They must then go through a landing examination conducted by inspection officers before they can obtain landing permission.
- ✘ They want to then go through a landing examination conducted by inspection officers before they can obtain landing permission.　<sub>情态：must → want to</sub>
- 依据：日文里有义务表达「〜なければならない／〜ないといけない」

## 轴：modal+person（3 题）

**16. 日文**：ジョンはこのところ酒を飲みすぎている。彼がこれ以上酒を飲むのをやめさせなければならない。　`matrix_2x2`

- ✔ John drinks too much these days. We have to stop him from drinking any more.
- ✘ John drinks too much these days. We have to stop me from drinking any more.　<sub>人称：him → me</sub>
- ✘ John drinks too much these days. We may stop him from drinking any more.　<sub>情态：have to → may</sub>
- ✘ John drinks too much these days. We may stop me from drinking any more.　<sub>情态：have to → may；人称：him → me</sub>
- 依据：日文里有义务表达「〜なければならない／〜ないといけない」；日文里显式出现了代词（彼），人称不是靠上下文猜的

**17. 日文**：我々は太陽エネルギーを最大限に活用しなければならない。　`matrix_2x2`

- ✘ They must make the best use of solar energy.　<sub>人称：We → they</sub>
- ✘ They may make the best use of solar energy.　<sub>情态：must → may；人称：We → they</sub>
- ✔ We must make the best use of solar energy.
- ✘ We may make the best use of solar energy.　<sub>情态：must → may</sub>
- 依据：日文里有义务表达「〜なければならない／〜ないといけない」；日文里显式出现了代词（私たち），人称不是靠上下文猜的

**18. 日文**：あなたはもっと仕事をしなければなりません。　`matrix_2x2`

- ✔ You must work more.
- ✘ I may work more.　<sub>情态：must → may；人称：You → I</sub>
- ✘ I must work more.　<sub>人称：You → I</sub>
- ✘ You may work more.　<sub>情态：must → may</sub>
- 依据：日文里有义务表达「〜なければならない／〜ないといけない」；日文里显式出现了代词（あなた／君），人称不是靠上下文猜的

## 轴：modal+time（3 题）

**19. 日文**：来月は、損失を取り返さねばならない。　`matrix_2x2`

- ✘ The loss may be made up for last month.　<sub>情态：must → may；时间：next month → last month</sub>
- ✘ The loss may be made up for next month.　<sub>情态：must → may</sub>
- ✔ The loss must be made up for next month.
- ✘ The loss must be made up for last month.　<sub>时间：next month → last month</sub>
- 依据：日文里有义务表达「〜なければならない／〜ないといけない」；日文里出现時間名詞「来月」，时间点是显式的

**20. 日文**：だいたい何でこんな真夜中にジュース買う為にパシらされなきゃなんないんだか・・・。　`matrix_2x2`

- ✘ Anyhow, just why is it that I may be sent out in the middle of the night to buy a canned drink?　<sub>情态：have to → may</sub>
- ✘ Anyhow, just why is it that I have to be sent out in the middle of the morning to buy a canned drink?　<sub>时间：night → morning</sub>
- ✔ Anyhow, just why is it that I have to be sent out in the middle of the night to buy a canned drink?
- ✘ Anyhow, just why is it that I may be sent out in the middle of the morning to buy a canned drink?　<sub>情态：have to → may；时间：night → morning</sub>
- 依据：日文里有义务表达「〜なければならない／〜ないといけない」；日文里出现時間名詞「夜」，时间点是显式的

**21. 日文**：手紙を書かなければならないが、明日まではそこまで手が回らない。　`matrix_2x2`

- ✘ I may write a letter, but I won't be able to get at it until yesterday.　<sub>情态：have to → may；时间：tomorrow → yesterday</sub>
- ✘ I have to write a letter, but I won't be able to get at it until yesterday.　<sub>时间：tomorrow → yesterday</sub>
- ✘ I may write a letter, but I won't be able to get at it until tomorrow.　<sub>情态：have to → may</sub>
- ✔ I have to write a letter, but I won't be able to get at it until tomorrow.
- 依据：日文里有义务表达「〜なければならない／〜ないといけない」；日文里出现時間名詞「明日」，时间点是显式的

## 轴：number（3 题）

**22. 日文**：バスは１０分おきに来ます。　`four_way_slot`

- ✘ Buses come every eleven minutes.　<sub>数量：ten → eleven</sub>
- ✔ Buses come every ten minutes.
- ✘ Buses come every nine minutes.　<sub>数量：ten → nine</sub>
- ✘ Buses come every twelve minutes.　<sub>数量：ten → twelve</sub>
- 依据：日文里出现数词「10」，数量是显式的

**23. 日文**：学生３枚ください。これが学生証です。　`four_way_slot`

- ✘ Two students. Here's my student ID.　<sub>数量：Three → two</sub>
- ✘ Four students. Here's my student ID.　<sub>数量：Three → four</sub>
- ✔ Three students. Here's my student ID.
- ✘ Five students. Here's my student ID.　<sub>数量：Three → five</sub>
- 依据：日文里出现数词「3」，数量是显式的

**24. 日文**：父は母より２歳若い。　`four_way_slot`

- ✘ 我父亲比我母亲小4岁。　<sub>数量：2 → 4</sub>
- ✔ 我父亲比我母亲小2岁。
- ✘ 我父亲比我母亲小1岁。　<sub>数量：2 → 1</sub>
- ✘ 我父亲比我母亲小3岁。　<sub>数量：2 → 3</sub>
- 依据：日文里出现数词「2」，数量是显式的

## 轴：number+time（3 题）

**25. 日文**：父は朝7時の地下鉄で通勤する。　`matrix_2x2`

- ✘ 爸爸乘中午8点的地铁去上班。　<sub>数量：7 → 8；时间：早上 → 中午</sub>
- ✘ 爸爸乘中午7点的地铁去上班。　<sub>时间：早上 → 中午</sub>
- ✘ 爸爸乘早上8点的地铁去上班。　<sub>数量：7 → 8</sub>
- ✔ 爸爸乘早上7点的地铁去上班。
- 依据：日文里出现数词「7」，数量是显式的；日文里出现時間名詞「朝」，时间点是显式的

**26. 日文**：昨日は一日中懸命に働いた。　`matrix_2x2`

- ✔ 昨天，我一整天都在工作。
- ✘ 今天，我两整天都在工作。　<sub>数量：一 → 两；时间：昨天 → 今天</sub>
- ✘ 昨天，我两整天都在工作。　<sub>数量：一 → 两</sub>
- ✘ 今天，我一整天都在工作。　<sub>时间：昨天 → 今天</sub>
- 依据：日文里出现数词「1」，数量是显式的；日文里出现時間名詞「昨日」，时间点是显式的

**27. 日文**：今朝、山羽さんが卸で胡桃を３０キロ買いました。　`matrix_2x2`

- ✔ This morning, Mr Yamaha bought 30 kilos of walnuts wholesale.
- ✘ Last night, Mr Yamaha bought 40 kilos of walnuts wholesale.　<sub>数量：30 → 40；时间：This morning → last night</sub>
- ✘ This morning, Mr Yamaha bought 40 kilos of walnuts wholesale.　<sub>数量：30 → 40</sub>
- ✘ Last night, Mr Yamaha bought 30 kilos of walnuts wholesale.　<sub>时间：This morning → last night</sub>
- 依据：日文里出现数词「30」，数量是显式的；日文里出现時間名詞「今朝」，时间点是显式的

## 轴：person（3 题）

**28. 日文**：彼は若かったが、敏腕だった。　`four_way_slot`

- ✔ Young as he was, he was a man of ability.
- ✘ Young as I was, I was a man of ability.　<sub>人称：he → I</sub>
- ✘ Young as she was, she was a man of ability.　<sub>人称：he → she</sub>
- ✘ Young as you were, you were a man of ability.　<sub>人称：he → you</sub>
- 依据：日文里显式出现了代词（彼），人称不是靠上下文猜的

**29. 日文**：彼は紅茶を注文した。　`four_way_slot`

- ✘ 她點了一杯茶。　<sub>人称：他 → 她</sub>
- ✘ 你點了一杯茶。　<sub>人称：他 → 你</sub>
- ✔ 他點了一杯茶。
- ✘ 我點了一杯茶。　<sub>人称：他 → 我</sub>
- 依据：日文里显式出现了代词（彼）

**30. 日文**：私は仕事で忙しい。　`four_way_slot`

- ✔ I'm busy with work.
- ✘ You're busy with work.　<sub>人称：I → you</sub>
- ✘ He's busy with work.　<sub>人称：I → he</sub>
- ✘ She's busy with work.　<sub>人称：I → she</sub>
- 依据：日文里显式出现了代词（私／僕），人称不是靠上下文猜的

## 轴：person+number（3 题）

**31. 日文**：列車は１０時半に出発するから、１０時にあなたを誘いに行きます。　`matrix_2x2`

- ✔ The train leaves at half past ten, so I'll call for you at ten.
- ✘ The train leaves at half past eleven, so I'll call for him at ten.　<sub>人称：you → him；数量：ten → eleven</sub>
- ✘ The train leaves at half past ten, so I'll call for him at ten.　<sub>人称：you → him</sub>
- ✘ The train leaves at half past eleven, so I'll call for you at ten.　<sub>数量：ten → eleven</sub>
- 依据：日文里显式出现了代词（あなた／君），人称不是靠上下文猜的；日文里出现数词「10」，数量是显式的

**32. 日文**：私は１９７２年１０月１０日に生まれました。　`matrix_2x2`

- ✘ 你在一九七二年八月十日出生。　<sub>人称：我 → 你；数量：十 → 八</sub>
- ✘ 我在一九七二年八月十日出生。　<sub>数量：十 → 八</sub>
- ✔ 我在一九七二年十月十日出生。
- ✘ 你在一九七二年十月十日出生。　<sub>人称：我 → 你</sub>
- 依据：日文里显式出现了代词（私／僕）；日文里出现数词「10」，数量是显式的

**33. 日文**：彼は昨日は一晩中勉強しました。　`matrix_2x2`

- ✘ 我昨天念了一整晚的書。　<sub>人称：他 → 我</sub>
- ✘ 他昨天念了两整晚的書。　<sub>数量：一 → 两</sub>
- ✘ 我昨天念了两整晚的書。　<sub>人称：他 → 我；数量：一 → 两</sub>
- ✔ 他昨天念了一整晚的書。
- 依据：日文里显式出现了代词（彼）；日文里出现数词「1」，数量是显式的

## 轴：person+time（3 题）

**34. 日文**：彼は今日は休みです。　`matrix_2x2`

- ✘ 他昨天放假。　<sub>时间：今天 → 昨天</sub>
- ✔ 他今天放假。
- ✘ 我昨天放假。　<sub>人称：他 → 我；时间：今天 → 昨天</sub>
- ✘ 我今天放假。　<sub>人称：他 → 我</sub>
- 依据：日文里显式出现了代词（彼）；日文里出现時間名詞「今日」，时间点是显式的

**35. 日文**：私の父は来年の春退職します。　`matrix_2x2`

- ✘ 你爸爸明年春天就要退休了。　<sub>人称：我 → 你</sub>
- ✘ 我爸爸今年春天就要退休了。　<sub>时间：明年 → 今年</sub>
- ✘ 你爸爸今年春天就要退休了。　<sub>人称：我 → 你；时间：明年 → 今年</sub>
- ✔ 我爸爸明年春天就要退休了。
- 依据：日文里显式出现了代词（私／僕）；日文里出现時間名詞「来年」，时间点是显式的

**36. 日文**：私は先週中国語を習い始めました。　`matrix_2x2`

- ✘ 你上周开始学中文了。　<sub>人称：我 → 你</sub>
- ✘ 你这周开始学中文了。　<sub>人称：我 → 你；时间：上周 → 这周</sub>
- ✔ 我上周开始学中文了。
- ✘ 我这周开始学中文了。　<sub>时间：上周 → 这周</sub>
- 依据：日文里显式出现了代词（私／僕）；日文里出现時間名詞「先週」，时间点是显式的

## 轴：polarity+conj（3 题）

**37. 日文**：私は文を書く前に頭の中で整えることにしている。　`matrix_2x2`

- ✘ I don't make a point of arranging sentences in my mind after writing them down.　<sub>肯否：make → don't make；分句逻辑：before → after</sub>
- ✔ I make a point of arranging sentences in my mind before writing them down.
- ✘ I make a point of arranging sentences in my mind after writing them down.　<sub>分句逻辑：before → after</sub>
- ✘ I don't make a point of arranging sentences in my mind before writing them down.　<sub>肯否：make → don't make</sub>
- 依据：日文句里没有任何否定形态素（ない／ぬ／ません），句尾谓语是肯定的；日文里有「〜前に」，先后顺序是显式的

**38. 日文**：日没前に仕事を終えるよう全力をつくしてやった。　`matrix_2x2`

- ✘ We didn't go all out to finish the work after dark.　<sub>肯否：went → didn't go；分句逻辑：before → after</sub>
- ✘ We didn't go all out to finish the work before dark.　<sub>肯否：went → didn't go</sub>
- ✔ We went all out to finish the work before dark.
- ✘ We went all out to finish the work after dark.　<sub>分句逻辑：before → after</sub>
- 依据：日文句里没有任何否定形态素（ない／ぬ／ません），句尾谓语是肯定的；日文里有「〜前に」，先后顺序是显式的

**39. 日文**：出来れば、釣りに行きたい。　`matrix_2x2`

- ✔ I'd like to go fishing if possible.
- ✘ I wouldn't like to go fishing if possible.　<sub>肯否：'d →  wouldn't</sub>
- ✘ I'd like to go fishing even if possible.　<sub>分句逻辑：if → even if</sub>
- ✘ I wouldn't like to go fishing even if possible.　<sub>肯否：'d →  wouldn't；分句逻辑：if → even if</sub>
- 依据：日文句里没有任何否定形态素（ない／ぬ／ません），句尾谓语是肯定的；日文里有条件形「〜たら／〜ば／〜なら」

## 轴：polarity+direction（3 题）

**40. 日文**：彼女はボストンからシカゴ経由でサンフランシスコへ旅行した。　`matrix_2x2`

- ✔ She traveled from Boston to San Francisco via Chicago.
- ✘ She didn't travel from San Francisco to Boston via Chicago.　<sub>肯否：traveled → didn't travel；起讫点：from Boston to San Francisco → from San Francisco to Boston</sub>
- ✘ She traveled from San Francisco to Boston via Chicago.　<sub>起讫点：from Boston to San Francisco → from San Francisco to Boston</sub>
- ✘ She didn't travel from Boston to San Francisco via Chicago.　<sub>肯否：traveled → didn't travel</sub>
- 依据：日文句里没有任何否定形态素（ない／ぬ／ません），句尾谓语是肯定的；日文用「〜から」「〜へ／まで」显式标出了起点和终点

**41. 日文**：彼女は一から十まで数えることができる。　`matrix_2x2`

- ✘ She cannot count from ten to one.　<sub>肯否：can → cannot；起讫点：from one to ten → from ten to one</sub>
- ✘ She cannot count from one to ten.　<sub>肯否：can → cannot</sub>
- ✔ She can count from one to ten.
- ✘ She can count from ten to one.　<sub>起讫点：from one to ten → from ten to one</sub>
- 依据：日文句里没有任何否定形态素（ない／ぬ／ません），句尾谓语是肯定的；日文用「〜から」「〜へ／まで」显式标出了起点和终点

**42. 日文**：その道は東京から大阪まで続いている。　`matrix_2x2`

- ✘ The road doesn't run from Tokyo to Osaka.　<sub>肯否：runs → doesn't run</sub>
- ✔ The road runs from Tokyo to Osaka.
- ✘ The road doesn't run from Osaka to Tokyo.　<sub>肯否：runs → doesn't run；起讫点：from Tokyo to Osaka → from Osaka to Tokyo</sub>
- ✘ The road runs from Osaka to Tokyo.　<sub>起讫点：from Tokyo to Osaka → from Osaka to Tokyo</sub>
- 依据：日文句里没有任何否定形态素（ない／ぬ／ません），句尾谓语是肯定的；日文用「〜から」「〜へ／まで」显式标出了起点和终点

## 轴：polarity+modal（3 题）

**43. 日文**：あなたに会いたいという人がいます。　`matrix_2x2`

- ✘ 有一个人必须见你。　<sub>情态：想 → 必须</sub>
- ✘ 没有一个人想见你。　<sub>肯否：有 → 没有</sub>
- ✔ 有一个人想见你。
- ✘ 没有一个人必须见你。　<sub>肯否：有 → 没有；情态：想 → 必须</sub>
- 依据：日文句里没有任何否定形态素（ない／ぬ／ません），说的是肯定的事；日文里有愿望形「〜たい」

**44. 日文**：ケイさんという方がお目にかかりたいそうです。　`matrix_2x2`

- ✘ 没有位凱先生必须見你。　<sub>肯否：有 → 没有；情态：想 → 必须</sub>
- ✘ 有位凱先生必须見你。　<sub>情态：想 → 必须</sub>
- ✔ 有位凱先生想見你。
- ✘ 没有位凱先生想見你。　<sub>肯否：有 → 没有</sub>
- 依据：日文句里没有任何否定形态素（ない／ぬ／ません），说的是肯定的事；日文里有愿望形「〜たい」

**45. 日文**：こんなに悪い天候の中で登山するべきではない。　`matrix_2x2`

- ✔ You should not climb the mountain in such bad weather.
- ✘ You should climb the mountain in such bad weather.　<sub>肯否：not 被去掉</sub>
- ✘ You must climb the mountain in such bad weather.　<sub>肯否：not 被去掉；情态：should → must</sub>
- ✘ You must not climb the mountain in such bad weather.　<sub>情态：should → must</sub>
- 依据：日文句尾谓语带否定形态素（ない／ません／ぬ），录音说的是「没有／不」；日文里有建议表达「〜ほうがいい／〜べき」

## 轴：polarity+number（3 题）

**46. 日文**：可算名詞か不可算名詞かどちらかを従えている表現を2つ書け。　`matrix_2x2`

- ✘ Write two expressions that are not followed by either count or non-count nouns in conversation.　<sub>肯否：are → are not</sub>
- ✔ Write two expressions that are followed by either count or non-count nouns in conversation.
- ✘ Write three expressions that are followed by either count or non-count nouns in conversation.　<sub>数量：two → three</sub>
- ✘ Write three expressions that are not followed by either count or non-count nouns in conversation.　<sub>肯否：are → are not；数量：two → three</sub>
- 依据：日文句里没有任何否定形态素（ない／ぬ／ません），句尾谓语是肯定的；日文里出现数词「2」，数量是显式的

**47. 日文**：私たちは２時間歩いた。　`matrix_2x2`

- ✘ We didn't walk for three hours.　<sub>肯否：walked → didn't walk；数量：two → three</sub>
- ✘ We walked for three hours.　<sub>数量：two → three</sub>
- ✘ We didn't walk for two hours.　<sub>肯否：walked → didn't walk</sub>
- ✔ We walked for two hours.
- 依据：日文句里没有任何否定形态素（ない／ぬ／ません），句尾谓语是肯定的；日文里出现数词「2」，数量是显式的

**48. 日文**：冷蔵庫の中にバターが２ポンドある。　`matrix_2x2`

- ✘ There are three pounds of butter in the icebox.　<sub>数量：two → three</sub>
- ✘ There are not three pounds of butter in the icebox.　<sub>肯否：are → are not；数量：two → three</sub>
- ✘ There are not two pounds of butter in the icebox.　<sub>肯否：are → are not</sub>
- ✔ There are two pounds of butter in the icebox.
- 依据：日文句里没有任何否定形态素（ない／ぬ／ません），句尾谓语是肯定的；日文里出现数词「2」，数量是显式的

## 轴：polarity+person（3 题）

**49. 日文**：彼はどうしてもその金を受け取ろうとしなかった。　`matrix_2x2`

- ✘ I would take the money.　<sub>肯否：not 被去掉；人称：He → I</sub>
- ✘ I would not take the money.　<sub>人称：He → I</sub>
- ✔ He would not take the money.
- ✘ He would take the money.　<sub>肯否：not 被去掉</sub>
- 依据：日文句尾谓语带否定形态素（ない／ません／ぬ），录音说的是「没有／不」；日文里显式出现了代词（彼），人称不是靠上下文猜的

**50. 日文**：彼はタフな奴だったよ。　`matrix_2x2`

- ✔ He was a tough guy.
- ✘ He was not a tough guy.　<sub>肯否：was → was not</sub>
- ✘ I was not a tough guy.　<sub>肯否：was → was not；人称：He → I</sub>
- ✘ I was a tough guy.　<sub>人称：He → I</sub>
- 依据：日文句里没有任何否定形态素（ない／ぬ／ません），句尾谓语是肯定的；日文里显式出现了代词（彼），人称不是靠上下文猜的

**51. 日文**：彼女はテニスが好きで、テニスのコーチになった。　`matrix_2x2`

- ✔ 她喜欢网球并成为了一个网球教练。
- ✘ 我喜欢网球并没成为一个网球教练。　<sub>肯否：成为了 → 没成为；人称：她 → 我</sub>
- ✘ 她喜欢网球并没成为一个网球教练。　<sub>肯否：成为了 → 没成为</sub>
- ✘ 我喜欢网球并成为了一个网球教练。　<sub>人称：她 → 我</sub>
- 依据：日文句里没有任何否定形态素（ない／ぬ／ません），说的是肯定的事；日文里显式出现了代词（彼女）

## 轴：polarity+place（3 题）

**52. 日文**：その女性達は図書館の前にいる。　`matrix_2x2`

- ✘ The women are not behind a library.　<sub>肯否：are → are not；方位：in front of → behind</sub>
- ✘ The women are behind a library.　<sub>方位：in front of → behind</sub>
- ✘ The women are not in front of a library.　<sub>肯否：are → are not</sub>
- ✔ The women are in front of a library.
- 依据：日文句里没有任何否定形态素（ない／ぬ／ません），句尾谓语是肯定的；日文里出现方位名词「前」，位置关系是显式的

**53. 日文**：猫は車の下にいる。　`matrix_2x2`

- ✘ The cat is not under the car.　<sub>肯否：is → is not</sub>
- ✘ The cat is not on the car.　<sub>肯否：is → is not；方位：under → on</sub>
- ✔ The cat is under the car.
- ✘ The cat is on the car.　<sub>方位：under → on</sub>
- 依据：日文句里没有任何否定形态素（ない／ぬ／ません），句尾谓语是肯定的；日文里出现方位名词「下」，位置关系是显式的

**54. 日文**：友達の消しゴムが机の下に転がっていった。　`matrix_2x2`

- ✘ My friend’s eraser didn't go rolling on the desk.　<sub>肯否：went → didn't go；方位：under → on</sub>
- ✘ My friend’s eraser didn't go rolling under the desk.　<sub>肯否：went → didn't go</sub>
- ✘ My friend’s eraser went rolling on the desk.　<sub>方位：under → on</sub>
- ✔ My friend’s eraser went rolling under the desk.
- 依据：日文句里没有任何否定形态素（ない／ぬ／ません），句尾谓语是肯定的；日文里出现方位名词「下」，位置关系是显式的

## 轴：polarity+tense（3 题）

**55. 日文**：事態は急変した。　`matrix_2x2`

- ✘ There is not a sudden change in the situation.　<sub>时制：was → is；肯否：is → is not</sub>
- ✔ There was a sudden change in the situation.
- ✘ There is a sudden change in the situation.　<sub>时制：was → is</sub>
- ✘ There was not a sudden change in the situation.　<sub>肯否：was → was not</sub>
- 依据：日文句里没有任何否定形态素（ない／ぬ／ません），句尾谓语是肯定的；日文句尾带过去助動詞「た」（ました／だった），说的是已经发生的事

**56. 日文**：彼女はもうすぐ６０歳だ。　`matrix_2x2`

- ✔ She is close on sixty.
- ✘ She is not close on sixty.　<sub>肯否：is → is not</sub>
- ✘ She was close on sixty.　<sub>时制：is → was</sub>
- ✘ She was not close on sixty.　<sub>时制：is → was；肯否：was → was not</sub>
- 依据：日文句里没有任何否定形态素（ない／ぬ／ません），句尾谓语是肯定的；日文句里没有过去助動詞「た」，说的不是已经完成的事

**57. 日文**：私のいとこは私より少し年上です。　`matrix_2x2`

- ✘ My cousin was a little older than I.　<sub>时制：is → was</sub>
- ✔ My cousin is a little older than I.
- ✘ My cousin is not a little older than I.　<sub>肯否：is → is not</sub>
- ✘ My cousin was not a little older than I.　<sub>时制：is → was；肯否：was → was not</sub>
- 依据：日文句里没有任何否定形态素（ない／ぬ／ません），句尾谓语是肯定的；日文句里没有过去助動詞「た」，说的不是已经完成的事

## 轴：polarity+time（3 题）

**58. 日文**：トムは毎朝公園でジョギングをしている。　`matrix_2x2`

- ✔ Tom goes jogging in the park every morning.
- ✘ Tom doesn't go jogging in the park every morning.　<sub>肯否：goes → doesn't go</sub>
- ✘ Tom goes jogging in the park every noon.　<sub>时间：morning → noon</sub>
- ✘ Tom doesn't go jogging in the park every noon.　<sub>肯否：goes → doesn't go；时间：morning → noon</sub>
- 依据：日文句里没有任何否定形态素（ない／ぬ／ません），句尾谓语是肯定的；日文里出现時間名詞「朝」，时间点是显式的

**59. 日文**：明日は雨が降るでしょうか。　`matrix_2x2`

- ✘ 今天会下雨吗？　<sub>时间：明天 → 今天</sub>
- ✘ 今天不会下雨吗？　<sub>肯否：会 → 不会；时间：明天 → 今天</sub>
- ✔ 明天会下雨吗？
- ✘ 明天不会下雨吗？　<sub>肯否：会 → 不会</sub>
- 依据：日文句里没有任何否定形态素（ない／ぬ／ません），说的是肯定的事；日文里出现時間名詞「明日」，时间点是显式的

**60. 日文**：先週の土曜日、公園へ行った。　`matrix_2x2`

- ✘ 上個星期六我沒去公園。　<sub>肯否：去了 → 沒去</sub>
- ✘ 上個星期一我去了公園。　<sub>时间：星期六 → 星期一</sub>
- ✘ 上個星期一我沒去公園。　<sub>肯否：去了 → 沒去；时间：星期六 → 星期一</sub>
- ✔ 上個星期六我去了公園。
- 依据：日文句里没有任何否定形态素（ない／ぬ／ません），说的是肯定的事；日文里出现時間名詞「土曜日」，时间点是显式的

## 轴：quant+number（3 题）

**61. 日文**：そのパーティーに姿を見せたのは１０人だけだった。　`matrix_2x2`

- ✘ Also ten people showed up for the party.　<sub>频度量化：Only → also</sub>
- ✘ Also eleven people showed up for the party.　<sub>频度量化：Only → also；数量：ten → eleven</sub>
- ✘ Only eleven people showed up for the party.　<sub>数量：ten → eleven</sub>
- ✔ Only ten people showed up for the party.
- 依据：日文里有「だけ／しか」；日文里出现数词「10」，数量是显式的

**62. 日文**：バスタオルが１枚しかありません。　`matrix_2x2`

- ✘ 也有一條浴巾。　<sub>频度量化：只有 → 也有</sub>
- ✘ 也有两條浴巾。　<sub>频度量化：只有 → 也有；数量：一 → 两</sub>
- ✘ 只有两條浴巾。　<sub>数量：一 → 两</sub>
- ✔ 只有一條浴巾。
- 依据：日文里有「だけ／しか」；日文里出现数词「1」，数量是显式的

**63. 日文**：私は口だけが一つありますが、耳が２つあります。　`matrix_2x2`

- ✘ I only have three mouths, but I have two ears.　<sub>数量：one → three</sub>
- ✘ I also have three mouths, but I have two ears.　<sub>频度量化：only → also；数量：one → three</sub>
- ✘ I also have one mouth, but I have two ears.　<sub>频度量化：only → also</sub>
- ✔ I only have one mouth, but I have two ears.
- 依据：日文里有「だけ／しか」；日文里出现数词「1」，数量是显式的

## 轴：quant+person（3 题）

**64. 日文**：彼はもう帰宅しました。　`matrix_2x2`

- ✔ He has already gone home.
- ✘ I have already gone home.　<sub>人称：He → I</sub>
- ✘ He has not yet gone home.　<sub>频度量化：already → not yet</sub>
- ✘ I have not yet gone home.　<sub>频度量化：already → not yet；人称：He → I</sub>
- 依据：日文里有「もう／すでに」；日文里显式出现了代词（彼），人称不是靠上下文猜的

**65. 日文**：私の髪はまだ洗ったばかりで濡れていた。　`matrix_2x2`

- ✔ My hair was still wet from being washed.
- ✘ My hair was no longer wet from being washed.　<sub>频度量化：still → no longer</sub>
- ✘ Your hair was still wet from being washed.　<sub>人称：My → your</sub>
- ✘ Your hair was no longer wet from being washed.　<sub>频度量化：still → no longer；人称：My → your</sub>
- 依据：日文里有「まだ」；日文里显式出现了代词（私／僕），人称不是靠上下文猜的

**66. 日文**：学生のころ私はよく彼女に手紙を書いた。　`matrix_2x2`

- ✘ I never wrote to her when I was a student.　<sub>频度量化：often → never</sub>
- ✔ I often wrote to her when I was a student.
- ✘ I often wrote to you when I was a student.　<sub>人称：her → you</sub>
- ✘ I never wrote to you when I was a student.　<sub>频度量化：often → never；人称：her → you</sub>
- 依据：日文里有「よく」；日文里显式出现了代词（彼女），人称不是靠上下文猜的

## 轴：role+polarity（3 题）

**67. 日文**：彼は私を見ると逃げた。　`matrix_2x2`

- ✘ He didn't run away at the sight of me.　<sub>肯否：ran → didn't run</sub>
- ✘ I didn't run away at the sight of him.　<sub>施受：He ↔ me 施受互换；肯否：ran → didn't run</sub>
- ✘ I ran away at the sight of him.　<sub>施受：He ↔ me 施受互换</sub>
- ✔ He ran away at the sight of me.
- 依据：日文里表示对象的代词带「を/に」格助词，施受方向是显式的；日文句里没有任何否定形态素（ない／ぬ／ません），句尾谓语是肯定的

**68. 日文**：彼女は私をバレエに招待してくれた。　`matrix_2x2`

- ✘ She didn't invite me to the ballet.　<sub>肯否：invited → didn't invite</sub>
- ✘ I didn't invite her to the ballet.　<sub>施受：She ↔ me 施受互换；肯否：invited → didn't invite</sub>
- ✘ I invited her to the ballet.　<sub>施受：She ↔ me 施受互换</sub>
- ✔ She invited me to the ballet.
- 依据：日文里表示对象的代词带「を/に」格助词，施受方向是显式的；日文句里没有任何否定形态素（ない／ぬ／ません），句尾谓语是肯定的

**69. 日文**：彼は私にプレゼントを送ってくれた。　`matrix_2x2`

- ✘ I didn't send him a present.　<sub>施受：He ↔ me 施受互换；肯否：sent → didn't send</sub>
- ✘ I sent him a present.　<sub>施受：He ↔ me 施受互换</sub>
- ✘ He didn't send me a present.　<sub>肯否：sent → didn't send</sub>
- ✔ He sent me a present.
- 依据：日文里表示对象的代词带「を/に」格助词，施受方向是显式的；日文句里没有任何否定形态素（ない／ぬ／ません），句尾谓语是肯定的

## 轴：role+tense（3 题）

**70. 日文**：彼女は彼に食べ過ぎないように忠告した。　`matrix_2x2`

- ✘ He will advise her not to eat too much.　<sub>施受：She ↔ him 施受互换；时制：advised → will advise</sub>
- ✘ He advised her not to eat too much.　<sub>施受：She ↔ him 施受互换</sub>
- ✘ She will advise him not to eat too much.　<sub>时制：advised → will advise</sub>
- ✔ She advised him not to eat too much.
- 依据：日文里表示对象的代词带「を/に」格助词，施受方向是显式的；日文句尾带过去助動詞「た」（ました／だった），说的是已经发生的事

**71. 日文**：彼女は彼をナイフで殺した。　`matrix_2x2`

- ✘ 他用一把刀杀会死她。　<sub>施受：她 ↔ 他 互换；时制：死了 → 会死</sub>
- ✔ 她用一把刀杀死了他。
- ✘ 她用一把刀杀会死他。　<sub>时制：死了 → 会死</sub>
- ✘ 他用一把刀杀死了她。　<sub>施受：她 ↔ 他 互换</sub>
- 依据：日文里表示对象的代词带「を／に」格助词，谁对谁做是显式的；日文句尾带过去助動詞「た」（ました／だった），说的是已经发生的事

**72. 日文**：私は彼に運転しないように助言した。　`matrix_2x2`

- ✔ I advised him not to drive.
- ✘ I will advise him not to drive.　<sub>时制：advised → will advise</sub>
- ✘ He advised me not to drive.　<sub>施受：I ↔ him 施受互换</sub>
- ✘ He will advise me not to drive.　<sub>施受：I ↔ him 施受互换；时制：advised → will advise</sub>
- 依据：日文里表示对象的代词带「を/に」格助词，施受方向是显式的；日文句尾带过去助動詞「た」（ました／だった），说的是已经发生的事

## 轴：tense+number（3 题）

**73. 日文**：１０人もの学生が全く同時に立ち上がった。　`matrix_2x2`

- ✘ As many as ten students will stand up all at once.　<sub>时制：stood → will stand</sub>
- ✘ As many as eleven students stood up all at once.　<sub>数量：ten → eleven</sub>
- ✘ As many as eleven students will stand up all at once.　<sub>时制：stood → will stand；数量：ten → eleven</sub>
- ✔ As many as ten students stood up all at once.
- 依据：日文句尾带过去助動詞「た」（ました／だった），说的是已经发生的事；日文里出现数词「10」，数量是显式的

**74. 日文**：この二つは大同小異だ。　`matrix_2x2`

- ✔ There is not much difference between the two.
- ✘ There was not much difference between the two.　<sub>时制：is → was</sub>
- ✘ There is not much difference between the three.　<sub>数量：two → three</sub>
- ✘ There was not much difference between the three.　<sub>时制：is → was；数量：two → three</sub>
- 依据：日文句里没有过去助動詞「た」，说的不是已经完成的事；日文里出现数词「2」，数量是显式的

**75. 日文**：電車は５番ホームに到着します。　`matrix_2x2`

- ✔ 列车将停靠在5号站台。
- ✘ 列车停了靠在6号站台。　<sub>时制：将停 → 停了；数量：5 → 6</sub>
- ✘ 列车将停靠在6号站台。　<sub>数量：5 → 6</sub>
- ✘ 列车停了靠在5号站台。　<sub>时制：将停 → 停了</sub>
- 依据：日文句里没有过去助動詞「た」，说的不是已经完成的事；日文里出现数词「5」，数量是显式的

## 轴：tense+person（3 题）

**76. 日文**：彼女は、ひとこともわからなかった。　`matrix_2x2`

- ✘ I failed to understand a single word.　<sub>人称：She → I</sub>
- ✔ She failed to understand a single word.
- ✘ I will fail to understand a single word.　<sub>时制：failed → will fail；人称：She → I</sub>
- ✘ She will fail to understand a single word.　<sub>时制：failed → will fail</sub>
- 依据：日文句尾带过去助動詞「た」（ました／だった），说的是已经发生的事；日文里显式出现了代词（彼女），人称不是靠上下文猜的

**77. 日文**：彼は机の上に本を置いた。　`matrix_2x2`

- ✘ 我把书放在了桌上。　<sub>人称：他 → 我</sub>
- ✔ 他把书放在了桌上。
- ✘ 他把书会放在桌上。　<sub>时制：放在了 → 会放在</sub>
- ✘ 我把书会放在桌上。　<sub>时制：放在了 → 会放在；人称：他 → 我</sub>
- 依据：日文句尾带过去助動詞「た」（ました／だった），说的是已经发生的事；日文里显式出现了代词（彼）

**78. 日文**：私は夜更かしをしないことにしている。　`matrix_2x2`

- ✘ I made it a rule not to sit up late.　<sub>时制：make → made</sub>
- ✔ I make it a rule not to sit up late.
- ✘ You made it a rule not to sit up late.　<sub>时制：make → made；人称：I → you</sub>
- ✘ You make it a rule not to sit up late.　<sub>人称：I → you</sub>
- 依据：日文句里没有过去助動詞「た」，说的不是已经完成的事；日文里显式出现了代词（私／僕），人称不是靠上下文猜的

## 轴：tense+quant（3 题）

**79. 日文**：解決しなければならない問題がたくさんある。　`matrix_2x2`

- ✘ There are few problems to solve.　<sub>频度量化：many → few</sub>
- ✘ There were many problems to solve.　<sub>时制：are → were</sub>
- ✘ There were few problems to solve.　<sub>时制：are → were；频度量化：many → few</sub>
- ✔ There are many problems to solve.
- 依据：日文句里没有过去助動詞「た」，说的不是已经完成的事；日文里有「たくさん／多く」

**80. 日文**：最終的に2人だけが残った。　`matrix_2x2`

- ✘ In the end also 2 people will remain.　<sub>时制：remained → will remain；频度量化：only → also</sub>
- ✘ In the end only 2 people will remain.　<sub>时制：remained → will remain</sub>
- ✘ In the end also 2 people remained.　<sub>频度量化：only → also</sub>
- ✔ In the end only 2 people remained.
- 依据：日文句尾带过去助動詞「た」（ました／だった），说的是已经发生的事；日文里有「だけ／しか」

**81. 日文**：当社は、品質の良いものしか販売しておりません。　`matrix_2x2`

- ✘ Our company also sells quality goods.　<sub>频度量化：only → also</sub>
- ✘ Our company only sold quality goods.　<sub>时制：sells → sold</sub>
- ✔ Our company only sells quality goods.
- ✘ Our company also sold quality goods.　<sub>时制：sells → sold；频度量化：only → also</sub>
- 依据：日文句里没有过去助動詞「た」，说的不是已经完成的事；日文里有「だけ／しか」

## 轴：time（3 题）

**82. 日文**：昨日学校を休んだ理由をいいなさい。　`four_way_slot`

- ✔ Tell me the reason for your absence from school yesterday.
- ✘ Tell me the reason for your absence from school the day after tomorrow.　<sub>时间：yesterday → the day after tomorrow</sub>
- ✘ Tell me the reason for your absence from school today.　<sub>时间：yesterday → today</sub>
- ✘ Tell me the reason for your absence from school tomorrow.　<sub>时间：yesterday → tomorrow</sub>
- 依据：日文里出现時間名詞「昨日」，时间点是显式的

**83. 日文**：今日のビールを取るか、明日の学位を取るか。　`four_way_slot`

- ✘ A beer yesterday or a degree tomorrow?　<sub>时间：today → yesterday</sub>
- ✘ A beer the day before yesterday or a degree tomorrow?　<sub>时间：today → the day before yesterday</sub>
- ✔ A beer today or a degree tomorrow?
- ✘ A beer the day after tomorrow or a degree tomorrow?　<sub>时间：today → the day after tomorrow</sub>
- 依据：日文里出现時間名詞「今日」，时间点是显式的

**84. 日文**：昨日は小雨が降った。　`four_way_slot`

- ✘ 今天下小雨。　<sub>时间：昨天 → 今天</sub>
- ✘ 明天下小雨。　<sub>时间：昨天 → 明天</sub>
- ✘ 后天下小雨。　<sub>时间：昨天 → 后天</sub>
- ✔ 昨天下小雨。
- 依据：日文里出现時間名詞「昨日」，时间点是显式的

## 轴：quant+tense（2 题）

**85. 日文**：全てを捨ててこのレストランをやる目的はひとつだけでした。　`matrix_2x2`

- ✘ I had also one aim in throwing everything away to run this restaurant.　<sub>频度量化：only → also</sub>
- ✘ I will have only one aim in throwing everything away to run this restaurant.　<sub>时制：had → will have</sub>
- ✔ I had only one aim in throwing everything away to run this restaurant.
- ✘ I will have also one aim in throwing everything away to run this restaurant.　<sub>频度量化：only → also；时制：had → will have</sub>
- 依据：日文里有「だけ／しか」；日文句尾带过去助動詞「た」（ました／だった），说的是已经发生的事

**86. 日文**：映画はもう始まりましたか。　`matrix_2x2`

- ✘ 电影还没会开始吗？　<sub>频度量化：已经 → 还没；时制：开始了 → 会开始</sub>
- ✘ 电影还没开始了吗？　<sub>频度量化：已经 → 还没</sub>
- ✔ 电影已经开始了吗？
- ✘ 电影已经会开始吗？　<sub>时制：开始了 → 会开始</sub>
- 依据：日文里有「もう／すでに」；日文句尾带过去助動詞「た」（ました／だった），说的是已经发生的事

## 轴：quant+time（2 题）

**87. 日文**：「昨日の今日だし・・・その・・・性器が痛かったりは？」「まだ、少しヒリヒリしますけど」　`matrix_2x2`

- ✘ "It's right after tomorrow so... that is... do your genitals hurt or...?" "It no longer smarts a little but..."　<sub>频度量化：still → no longer；时间：yesterday → tomorrow</sub>
- ✘ "It's right after yesterday so... that is... do your genitals hurt or...?" "It no longer smarts a little but..."　<sub>频度量化：still → no longer</sub>
- ✘ "It's right after tomorrow so... that is... do your genitals hurt or...?" "It still smarts a little but..."　<sub>时间：yesterday → tomorrow</sub>
- ✔ "It's right after yesterday so ... that is ... do your genitals hurt or ...?" "It still smarts a little but..."
- 依据：日文里有「まだ」；日文里出现時間名詞「昨日」，时间点是显式的

**88. 日文**：今日しなければならない宿題がたくさんある。　`matrix_2x2`

- ✔ I have a lot of assignments to do today.
- ✘ I have a lot of assignments to do yesterday.　<sub>时间：today → yesterday</sub>
- ✘ I have a little assignments to do yesterday.　<sub>频度量化：a lot of → a little；时间：today → yesterday</sub>
- ✘ I have a little assignments to do today.　<sub>频度量化：a lot of → a little</sub>
- 依据：日文里有「たくさん／多く」；日文里出现時間名詞「今日」，时间点是显式的

## 轴：tense+time（2 题）

**89. 日文**：昨日はでかけないで読書で日を過ごした。　`matrix_2x2`

- ✘ I will spend today reading instead of going out.　<sub>时制：spent → will spend；时间：yesterday → today</sub>
- ✔ I spent yesterday reading instead of going out.
- ✘ I spent today reading instead of going out.　<sub>时间：yesterday → today</sub>
- ✘ I will spend yesterday reading instead of going out.　<sub>时制：spent → will spend</sub>
- 依据：日文句尾带过去助動詞「た」（ました／だった），说的是已经发生的事；日文里出现時間名詞「昨日」，时间点是显式的

**90. 日文**：そんな事実にまったく悪びれることなく、千歳は今日も元気に過ごしております。　`matrix_2x2`

- ✔ Without flinching from that fact in the slightest, Chitose is spending today as well in fine spirit.
- ✘ Without flinching from that fact in the slightest, Chitose was spending yesterday as well in fine spirit.　<sub>时制：is → was；时间：today → yesterday</sub>
- ✘ Without flinching from that fact in the slightest, Chitose is spending yesterday as well in fine spirit.　<sub>时间：today → yesterday</sub>
- ✘ Without flinching from that fact in the slightest, Chitose was spending today as well in fine spirit.　<sub>时制：is → was</sub>
- 依据：日文句里没有过去助動詞「た」，说的不是已经完成的事；日文里出现時間名詞「今日」，时间点是显式的

## 轴：comparative+number（1 题）

**91. 日文**：彼は私よりも２インチ背が高い。　`matrix_2x2`

- ✘ 他比我高三寸。　<sub>数量：两 → 三</sub>
- ✘ 我比他高两寸。　<sub>比较方向：他 ↔ 我 互换</sub>
- ✔ 他比我高两寸。
- ✘ 我比他高三寸。　<sub>比较方向：他 ↔ 我 互换；数量：两 → 三</sub>
- 依据：日文用「〜より」显式标出了比较的基准，互换两侧后意思相反；日文里出现数词「2」，数量是显式的

## 轴：conj+number（1 题）

**92. 日文**：出発２０分前になったら、搭乗案内のアナウンスがかかるって。　`matrix_2x2`

- ✘ They said they'd make the boarding announcement 30 minutes after takeoff.　<sub>分句逻辑：before → after；数量：20 → 30</sub>
- ✘ They said they'd make the boarding announcement 20 minutes after takeoff.　<sub>分句逻辑：before → after</sub>
- ✘ They said they'd make the boarding announcement 30 minutes before takeoff.　<sub>数量：20 → 30</sub>
- ✔ They said they'd make the boarding announcement 20 minutes before takeoff.
- 依据：日文里有「〜前に」，先后顺序是显式的；日文里出现数词「20」，数量是显式的

## 轴：conj+quant（1 题）

**93. 日文**：彼は仕事が不安定なので、よく引っ越しをする。　`matrix_2x2`

- ✘ 他经常搬家，虽然他的工作不固定。　<sub>分句逻辑：因为 → 虽然</sub>
- ✔ 他经常搬家，因为他的工作不固定。
- ✘ 他从不搬家，虽然他的工作不固定。　<sub>分句逻辑：因为 → 虽然；频度量化：经常 → 从不</sub>
- ✘ 他从不搬家，因为他的工作不固定。　<sub>频度量化：经常 → 从不</sub>
- 依据：日文里有表示原因的「から／ので」，没有逆接的「のに／けど」；日文里有「よく」

## 轴：conj+tense（1 题）

**94. 日文**：公衆の面前に姿を見せなければならないのが厭だった。　`matrix_2x2`

- ✘ He was annoyed at having to show up after the public.　<sub>分句逻辑：before → after</sub>
- ✘ He is annoyed at having to show up after the public.　<sub>分句逻辑：before → after；时制：was → is</sub>
- ✔ He was annoyed at having to show up before the public.
- ✘ He is annoyed at having to show up before the public.　<sub>时制：was → is</sub>
- 依据：日文里有「〜前に」，先后顺序是显式的；日文句尾带过去助動詞「た」（ました／だった），说的是已经发生的事

## 轴：direction+conj（1 题）

**95. 日文**：新幹線なら、名古屋から東京もそんなに遠く感じないよ。　`matrix_2x2`

- ✘ Even if you travel by Shinkansen, it doesn't seem far from Nagoya to Tokyo.　<sub>分句逻辑：If → even if</sub>
- ✘ Even if you travel by Shinkansen, it doesn't seem far from Tokyo to Nagoya.　<sub>起讫点：from Nagoya to Tokyo → from Tokyo to Nagoya；分句逻辑：If → even if</sub>
- ✔ If you travel by Shinkansen, it doesn't seem far from Nagoya to Tokyo.
- ✘ If you travel by Shinkansen, it doesn't seem far from Tokyo to Nagoya.　<sub>起讫点：from Nagoya to Tokyo → from Tokyo to Nagoya</sub>
- 依据：日文用「〜から」「〜へ／まで」显式标出了起点和终点；日文里有条件形「〜たら／〜ば／〜なら」

## 轴：person+tense（1 题）

**96. 日文**：彼はわざとそうしたのではないかという考えが、ふと私の頭をよぎった。　`matrix_2x2`

- ✘ It occurred to you that he will have done it on purpose.　<sub>人称：me → you；时制：had → will have</sub>
- ✘ It occurred to you that he had done it on purpose.　<sub>人称：me → you</sub>
- ✔ It occurred to me that he had done it on purpose.
- ✘ It occurred to me that he will have done it on purpose.　<sub>时制：had → will have</sub>
- 依据：日文里显式出现了代词（私／僕），人称不是靠上下文猜的；日文句尾带过去助動詞「た」（ました／だった），说的是已经发生的事

## 轴：place+person（1 题）

**97. 日文**：彼は机を右に移動させた。　`matrix_2x2`

- ✔ 他往右边移了书桌。
- ✘ 我往右边移了书桌。　<sub>人称：他 → 我</sub>
- ✘ 我往左边移了书桌。　<sub>方位：右边 → 左边；人称：他 → 我</sub>
- ✘ 他往左边移了书桌。　<sub>方位：右边 → 左边</sub>
- 依据：日文里出现方位名词「右」，位置关系是显式的；日文里显式出现了代词（彼）

## 轴：quant（1 题）

**98. 日文**：それは決して消えることはない。　`four_way_slot`

- ✘ That will often disappear.　<sub>频度量化：never → often</sub>
- ✘ That will sometimes disappear.　<sub>频度量化：never → sometimes</sub>
- ✘ That will always disappear.　<sub>频度量化：never → always</sub>
- ✔ That will never disappear.
- 依据：日文里有「全然／決して」＋否定

## 轴：time+tense（1 题）

**99. 日文**：今日の昼はチャーハンを食べた。　`matrix_2x2`

- ✔ Today, I had fried rice for lunch.
- ✘ Today, I will have fried rice for lunch.　<sub>时制：had → will have</sub>
- ✘ Yesterday, I will have fried rice for lunch.　<sub>时间：Today → yesterday；时制：had → will have</sub>
- ✘ Yesterday, I had fried rice for lunch.　<sub>时间：Today → yesterday</sub>
- 依据：日文里出现時間名詞「今日」，时间点是显式的；日文句尾带过去助動詞「た」（ました／だった），说的是已经发生的事
